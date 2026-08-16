"""
JARVIS TRADER — Market Data Layer
===================================
Unified interface to IBKR, Polygon, and Finnhub.
Data waterfall: IBKR → Polygon → CSV cache → structured None (no silent zeros).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ib_async import Future

    from execution.schwab_connector import SchwabConnector

import pandas as pd

from data.polygon_stream import PolygonStreamer
from data.provenance import DEFAULT_STALE_AFTER_S, build_envelope

# Lazy import — bars_repository requires sqlite3 which is always available,
# but importing at module level makes the hot path slightly heavier; use a
# try/except so a missing file never crashes startup.
try:
    from data.bars_repository import load_bars as _load_bars
    from data.bars_repository import save_bars as _save_bars
except Exception:  # pragma: no cover
    _load_bars = None  # type: ignore[assignment]
    _save_bars = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Optional TradingView real-time feed — imported lazily so it never breaks startup
try:
    from data.tradingview_feed import TradingViewFeed as _TradingViewFeed

    _tv_feed = _TradingViewFeed()
except Exception:
    _tv_feed = None  # type: ignore[assignment]

# Continuous contract symbol mappings — single source of truth
# Polygon.io confirmed working symbols (tested 2026-04-05):
#   CL  = $85.41 ✅  (crude oil — proxy for MCL, same price different tick value)
#   NQ/ES/GC/MCL/MNQ/MES/MGC = no data on current plan ❌
# Micro futures use standard contract prices — tick value differs but price is identical.
FUTURES_MAP = {
    "MCL": "CL",  # Micro Crude Oil  → CL (same price, 1/10 contract size)
    "MNQ": "NQ",  # Micro Nasdaq-100 → NQ (same price, 1/10 contract size)
    "MES": "ES",  # Micro E-mini S&P → ES (same price, 1/10 contract size)
    "MGC": "GC",  # Micro Gold       → GC (same price, 1/10 contract size)
    "CL": "CL",
    "NQ": "NQ",
    "ES": "ES",
    "GC": "GC",
}

# ── Polygon Futures Map ─────────────────────────────────────────────────────
# DISABLED 2026-04-16 — incident: Polygon's `CL` ticker is Colgate-Palmolive
# Company stock (NYSE: CL, type=CS), NOT crude oil futures. Same trap exists
# for `NQ`, `ES`, `GC` (different stocks each, all NOT the futures you'd expect).
# The 2026-04-05 audit comment ("CL = $85.41 ✅ crude oil") was wrong — that
# $85.41 was Colgate-Palmolive's stock price, not crude.
#
# Polygon's free plan does NOT include futures data at all (only stocks/ETFs).
# To prevent silent data corruption (consumer-goods stock prices treated as
# crude oil ticks), this map is intentionally empty and callers MUST check
# POLYGON_FUTURES_BLOCKLIST before hitting Polygon.
#
# Re-enable only after subscribing to a Polygon plan that includes futures
# AND verifying the correct ticker format (e.g. `I:CL`, `C:CLF26`).
# See `docs/data-source-audit-2026-04-16.md` for the incident report and
# Task #15 (T1.5) for the backtest-metric contamination audit.
POLYGON_FUTURES_MAP: dict[str, str] = {
    # Empty by design. Adding a futures symbol here without verifying it
    # returns the correct underlying is a CRITICAL safety violation.
}

# Symbols Polygon free plan returns the WRONG asset for.
# Callers MUST check this set and skip Polygon for any match — empty result
# is preferred over silent stock-vs-futures data substitution.
POLYGON_FUTURES_BLOCKLIST: frozenset[str] = frozenset(
    {
        "MCL",
        "MNQ",
        "MES",
        "MGC",
        "M2K",
        "MYM",
        "CL",
        "NQ",
        "ES",
        "GC",
        "RTY",
        "YM",
        "SI",
        "ZB",
        "ZN",
    }
)

# Scale factors: micro price == standard price (same underlying price,
# just different notional/tick size), so factor is 1.0 for all.
FUTURES_SCALE_FACTOR = {
    "MCL": 1.0,  # CL and MCL track same crude price
    "MNQ": 1.0,  # NQ and MNQ track same Nasdaq price
    "MES": 1.0,  # ES and MES track same S&P price
    "MGC": 1.0,  # GC and MGC track same gold price
}

# Schwab-specific futures symbol map (Schwab uses slash-prefix)
SCHWAB_FUTURES_MAP = {
    "MCL": "/MCL",
    "MNQ": "/MNQ",
    "MES": "/MES",
    "MGC": "/MGC",
    "CL": "/CL",
    "NQ": "/NQ",
    "ES": "/ES",
    "GC": "/GC",
}

# IBKR exchange map for futures
FUTURES_EXCHANGE = {
    "MCL": "NYMEX",
    "CL": "NYMEX",
    "MNQ": "CME",
    "NQ": "CME",
    "MES": "CME",
    "ES": "CME",
    "MGC": "COMEX",
    "GC": "COMEX",
    # Copper trades on COMEX too (same default-to-CME trap as the bonds below).
    # MHG is declared in mtf_analyzer._FUTURES_SYMBOLS, so a live pull would break.
    "HG": "COMEX",
    "MHG": "COMEX",
    # CBOT (ECBOT) — Treasuries + grains + the Dow. Without these the lookup default
    # ("CME") builds a nonexistent CME contract → IB Error 200 "no security
    # definition" → contract=None → stale-cache fallback. (Bug 2026-06-26: froze the
    # ZB/ZN forward-shadow.) ZB/ZN are the live bond pair; YM/MYM (E-mini Dow, also in
    # mtf_analyzer._FUTURES_SYMBOLS) and the grains are mapped for correctness.
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
    "ZT": "CBOT",
    "ZC": "CBOT",
    "ZS": "CBOT",
    "ZW": "CBOT",
    "YM": "CBOT",
    "MYM": "CBOT",
}


class MarketDataBar:
    """Normalized OHLCV bar regardless of data source"""

    def __init__(
        self,
        symbol: str,
        timestamp: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        source: str,
    ):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.source = source


def resolve_data_client_id(config) -> int:
    """Distinct IB clientId for the DATA leg.

    IB Gateway refuses a second connection that reuses a clientId already held by
    a live connection. The execution leg (``execution/ibkr_executor.py``) connects
    with ``IBKR_CLIENT_ID``, so the data connector MUST NOT reuse it — sharing the
    id made the data leg collide with the executor and fail to connect. Honor an
    explicit ``IBKR_DATA_CLIENT_ID`` when set (non-zero), else offset the executor
    id by +1, matching the smoke/scanner convention elsewhere in the engine.
    """
    explicit = getattr(config, "IBKR_DATA_CLIENT_ID", 0) or 0
    try:
        explicit = int(explicit)
    except (TypeError, ValueError):
        explicit = 0
    return explicit if explicit > 0 else int(config.IBKR_CLIENT_ID) + 1


# --- Connect-failure log throttle (SOTA plan P0.6) --------------------------
# An extended IB Gateway outage used to log a fresh WARNING on every single
# connect() attempt for as long as the outage lasted — unbounded
# ConnectionRefused spam that kept the engine log regrowing at the source.
# Every ``IBDataWatchdog`` poll tick (and ``MarketDataManager.reconnect_ibkr``)
# rebuilds a brand-new ``IBKRDataConnector`` instance, so per-instance state
# alone can't throttle across ticks — this lives at module scope, keyed by
# (host, port), so it survives instance rebuilds. The first failure for a
# target always logs immediately (operators need to see the initial drop);
# subsequent failures are suppressed until an exponentially growing backoff
# elapses since the last real log line, at which point a single
# "still down, N suppressed" summary replaces the raw per-attempt detail.
_CONNECT_FAIL_LOG_BACKOFF_BASE_S = 5.0
_CONNECT_FAIL_LOG_BACKOFF_MAX_S = 300.0
_connect_fail_state: dict[tuple[str, int], dict] = {}

# Ceiling on any single IB *data* request (2026-08-15 incident).
#
# ``is_connected`` is only a local ``ib_async.IB.isConnected()`` socket check —
# it cannot tell a healthy Gateway from a wedged one. When the Gateway's API
# stops answering while the socket stays open, an unbounded ``await`` on
# reqTickersAsync/qualifyContractsAsync never returns and never raises, so the
# ``except`` branches below never run and Tiers 2-5 of the price waterfall
# (Schwab -> Polygon -> CSV cache) become unreachable. Every price-serving
# endpoint then hangs indefinitely rather than degrading to a stale mark.
#
# The connection path already bounds itself (see ``_connect_timeout``), and
# ``services/ib_freshness_heartbeat.py`` already wraps get_snapshot_price in
# ``wait_for(timeout=8.0)`` — this applies the same discipline to the request
# path so every caller inherits it. Sized for ~50x headroom over a typical
# sub-100ms snapshot: long enough that a merely-slow Gateway is not
# misreported as down, short enough that a wedge degrades instead of hangs.
_IBKR_DATA_REQUEST_TIMEOUT_S = float(os.getenv("IBKR_DATA_REQUEST_TIMEOUT_SECONDS", "5.0"))


def _reset_connect_fail_throttle(host: str | None = None, port: int | None = None) -> None:
    """Test/ops hook: clear throttle state for one target (or every target)."""
    if host is None and port is None:
        _connect_fail_state.clear()
    else:
        _connect_fail_state.pop((host, port), None)


def _log_connect_failure(host: str, port: int, client_id: int, detail: str) -> None:
    """Throttled WARNING for a failed IBKR connect() attempt.

    See the module-level note above for the rationale. Call once per failed
    connect() attempt (both the internal per-attempt retries and the final
    give-up); a caller in a tight failure loop collapses to one real log line
    plus periodic "still down, N suppressed" summaries instead of raw spam.
    """
    key = (host, port)
    state = _connect_fail_state.setdefault(key, {"streak": 0, "last_log": 0.0, "suppressed": 0})
    now = time.monotonic()
    state["streak"] += 1
    if state["streak"] == 1:
        logger.warning(detail)
        state["last_log"] = now
        state["suppressed"] = 0
        return

    backoff = min(
        _CONNECT_FAIL_LOG_BACKOFF_MAX_S,
        _CONNECT_FAIL_LOG_BACKOFF_BASE_S * (2 ** (state["streak"] - 2)),
    )
    if now - state["last_log"] < backoff:
        state["suppressed"] += 1
        return

    logger.warning(
        "IBKR still down (%s:%s, clientId=%s) — %d attempt(s) suppressed since "
        "last log, %d consecutive failure(s), next check backoff %.0fs",
        host,
        port,
        client_id,
        state["suppressed"],
        state["streak"],
        backoff,
    )
    state["last_log"] = now
    state["suppressed"] = 0


def _log_connect_recovery(host: str, port: int) -> None:
    """Clear throttle state on a successful connect(); note it if we'd been
    suppressing failures, so operators see the outage actually ended."""
    state = _connect_fail_state.pop((host, port), None)
    if state and state["streak"]:
        logger.info(
            "IBKR connect recovered (%s:%s) after %d failed attempt(s) (%d suppressed)",
            host,
            port,
            state["streak"],
            state["suppressed"],
        )


class IBKRDataConnector:
    """
    Connects to IB Gateway via ib_async.
    Paper mode: port 4002. Live: port 4001.
    Download IB Gateway: https://www.interactivebrokers.com/en/trading/ibgateway.php
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 1,
        connect_timeout: float = 5.0,
    ):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._connect_timeout = connect_timeout
        self._ib = None
        self._connected = False
        # Real-time bar subscriptions, replayed after a reconnect rebuilds the IB
        # client. No callers today (subscribe_real_time is unused) — kept so a
        # future streaming feed survives a watchdog reconnect.
        self._realtime_subs: list = []

    async def connect(self, retries: int = 2, retry_backoff: float = 2.0) -> bool:
        """Connect to IB Gateway, with a bounded retry on transient failures.

        ib_async's connectAsync has no built-in timeout on the TCP handshake and
        will block the FastAPI lifespan 30-120s when IB Gateway isn't listening,
        so each attempt is wrapped in asyncio.wait_for.

        A *timeout* means the Gateway isn't listening — we fail fast (no retry) so
        dev restarts with the Gateway stopped still bind port 8010 in seconds.
        A *non-timeout* failure (e.g. the Gateway momentarily rejecting a fresh
        connection while it settles the execution leg) is the kind that used to
        leave the data leg dead for the whole session, so those are retried a
        small bounded number of times with linear backoff. Each retry rebuilds
        the IB client and drops any half-open socket first so the clientId frees.
        ImportError (ib_async missing) is terminal and never retried.
        """
        try:
            from ib_async import IB
        except ImportError:
            logger.warning("ib_async not installed. Run: pip install ib_async")
            return False

        attempts = max(1, retries + 1)
        for attempt in range(1, attempts + 1):
            self._ib = IB()
            try:
                await asyncio.wait_for(
                    self._ib.connectAsync(self._host, self._port, clientId=self._client_id),
                    timeout=self._connect_timeout,
                )
                self._connected = True
                # Delayed-data stopgap for the IB paper-account market-data
                # subscription gap (Error 10168/354: futures data not subscribed).
                # reqMarketDataType(3) asks IB for DELAYED data when no live
                # subscription exists — IB still returns LIVE for any instrument
                # that IS subscribed, so this never downgrades a good live feed.
                # Without it the data leg errors and falls through to a months-old
                # CSV cache (the 2026-06-29 frozen-MES-5300 auto-approve fills).
                # 1=live 2=frozen 3=delayed 4=delayed-frozen; override via
                # IB_MARKET_DATA_TYPE. Non-fatal: a failure here must never abort
                # an otherwise-good connect.
                try:
                    _mdt = int(os.environ.get("IB_MARKET_DATA_TYPE", "3"))
                    if _mdt in (1, 2, 3, 4):
                        self._ib.reqMarketDataType(_mdt)
                        logger.info(
                            "IBKR market-data type set to %d "
                            "(1=live 2=frozen 3=delayed 4=delayed-frozen)",
                            _mdt,
                        )
                except Exception as _mdt_exc:
                    logger.warning("reqMarketDataType failed (non-fatal): %s", _mdt_exc)
                # Keep _connected honest on a mid-session drop so the per-call data
                # waterfall fails over immediately and the watchdog detects the drop.
                try:
                    self._ib.disconnectedEvent += self._on_disconnected
                except Exception:
                    pass
                logger.info(
                    f"IBKR connected {self._host}:{self._port} "
                    f"(clientId={self._client_id}, paper={self._port == 4002})"
                )
                _log_connect_recovery(self._host, self._port)
                return True
            except asyncio.TimeoutError:
                # Gateway not listening — fail fast, retrying would only stall startup.
                _log_connect_failure(
                    self._host,
                    self._port,
                    self._client_id,
                    f"IBKR connection timed out after {self._connect_timeout}s "
                    f"({self._host}:{self._port}, clientId={self._client_id}) — start IB "
                    f"Gateway or bump IBKR_CONNECT_TIMEOUT_SECONDS.",
                )
                self._connected = False
                return False
            except Exception as e:
                # Drop any half-open socket so the clientId is released before retrying.
                try:
                    self._ib.disconnect()
                except Exception:
                    pass
                if attempt < attempts:
                    _log_connect_failure(
                        self._host,
                        self._port,
                        self._client_id,
                        f"IBKR connect attempt {attempt}/{attempts} failed "
                        f"({self._host}:{self._port}, clientId={self._client_id}): {e} "
                        f"— retrying in {retry_backoff:.0f}s",
                    )
                    await asyncio.sleep(retry_backoff)
                else:
                    _log_connect_failure(
                        self._host,
                        self._port,
                        self._client_id,
                        f"IBKR connection failed after {attempts} attempt(s) "
                        f"({self._host}:{self._port}, clientId={self._client_id}): {e} "
                        f"— start IB Gateway on port {self._port}.",
                    )
        self._connected = False
        return False

    async def disconnect(self):
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False

    def _make_contract(self, symbol: str, is_futures: bool):
        from ib_async import Future, Index, Stock

        if symbol.upper() in ("VIX",):
            return Index(symbol, "CBOE")
        if is_futures or symbol.upper() in FUTURES_MAP:
            exchange = FUTURES_EXCHANGE.get(symbol.upper(), "CME")
            return Future(symbol, exchange=exchange, currency="USD")
        return Stock(symbol, "SMART", "USD")

    async def _qualified_contract(self, symbol: str, is_futures: bool):
        """
        Return a contract usable for market-data requests (tickers, historical, streaming).
        IB requires conId for hashing/subscriptions; qualify generic symbols via the API.
        """
        from ib_async import Contract

        exchange = FUTURES_EXCHANGE.get(symbol.upper(), "CME")
        if is_futures or symbol.upper() in FUTURES_MAP:
            c: Contract = await self._resolve_front_month(symbol, exchange)
        else:
            c = self._make_contract(symbol, is_futures)
        cid = getattr(c, "conId", 0) or 0
        if cid > 0:
            return c
        try:
            qualified = await self._ib.qualifyContractsAsync(c)
            if qualified:
                return qualified[0]
        except Exception as e:
            logger.warning(f"qualifyContractsAsync failed for {symbol}: {e}")
        return c

    async def _resolve_front_month(self, symbol: str, exchange: str) -> Future:
        """Resolve futures symbol to the nearest non-expired (front month) contract.

        IBKR's reqContractDetailsAsync returns *all* contracts including ones
        whose `lastTradeDateOrContractMonth` is already in the past. Sorting
        ascending and taking [0] therefore returns the most-recently-expired
        contract (e.g. MGCJ6 after 2026-04-28), and any historical query
        ending after that expiry returns "HMDS query returned no data".
        Fix: drop expired contracts before picking the front month.
        """
        from ib_async import Future

        generic = Future(symbol, exchange=exchange, currency="USD")
        try:
            details = await self._ib.reqContractDetailsAsync(generic)
            if details:
                today_yyyymmdd = date.today().strftime("%Y%m%d")
                live = [
                    d
                    for d in details
                    if (d.contract.lastTradeDateOrContractMonth or "") >= today_yyyymmdd
                ]
                if live:
                    live.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
                    return live[0].contract
                # Degenerate: nothing live. Fall back to the most-recent expired
                # so historical queries that end before today still resolve.
                details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth, reverse=True)
                return details[0].contract
        except Exception as e:
            logger.warning(f"Could not resolve front month for {symbol}: {e}")
        return generic

    async def get_historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "5 mins",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars from IBKR."""
        if not self._connected:
            return pd.DataFrame()
        try:
            contract = await self._qualified_contract(symbol, is_futures)
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=False,
            )
            if not bars:
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "timestamp": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    for bar in bars
                ]
            )
        except Exception as e:
            logger.warning(f"IBKR get_historical_bars failed for {symbol}: {e}")
            return pd.DataFrame()

    async def get_snapshot_price(self, symbol: str, is_futures: bool = False) -> dict:
        """Return a real-time snapshot price dict from IBKR.

        Primary: reqTickersAsync for real-time L1 data.
        Fallback: last historical bar close (1 D / 1 hour bars) when ticker
        subscription is unavailable (IB Error 354 — market data not subscribed).
        Historical bars always work on the paper account.
        """
        if not self._connected:
            return {
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "ibkr_not_connected",
            }
        try:
            # Always qualify before requesting a ticker snapshot. ib_async keys
            # in-flight market-data requests by conId; a generic/unqualified
            # Contract (conId=0) risks resolving to whatever other request is
            # outstanding when multiple symbols are snapshotted concurrently —
            # exactly what get_batch_prices() does (one reqTickersAsync per
            # watchlist symbol, fired together via asyncio.gather).
            # GT-17: AAPL's unqualified Stock contract picked up a futures
            # quote (~$7494, ~23x AAPL's real price) because it was requested
            # in the same batch as MES/MGC/etc, which resolve to a real conId
            # via _resolve_front_month. _qualified_contract already handles
            # both cases (front-month for futures, qualifyContractsAsync for
            # everything else) — reuse it instead of duplicating the branch
            # with an unqualified fallback for non-futures symbols.
            contract = await asyncio.wait_for(
                self._qualified_contract(symbol, is_futures),
                timeout=_IBKR_DATA_REQUEST_TIMEOUT_S,
            )
            tickers = await asyncio.wait_for(
                self._ib.reqTickersAsync(contract),
                timeout=_IBKR_DATA_REQUEST_TIMEOUT_S,
            )
            if tickers:
                t = tickers[0]
                last = (
                    t.last
                    if t.last and t.last > 0
                    else (t.close if t.close and t.close > 0 else None)
                )
                prev = t.close if t.close and t.close > 0 else None
                change_pct = ((last - prev) / prev * 100) if last and prev and prev > 0 else None
                if last:
                    # marketDataType 3/4 = Delayed/Delayed-frozen (IB serves this
                    # when the account lacks a live subscription). A 15-20min-old
                    # futures quote is stale in the same way a frozen CSV cache is
                    # (see entry_price_sanity.py's offline-fallback anchor) but
                    # carries no timestamp signal distinguishing it from a live
                    # tick, so it must be tagged at the source instead.
                    is_delayed = getattr(t, "marketDataType", 1) in (3, 4)
                    return {
                        "last_price": last,
                        "prev_close": prev,
                        "change_pct": change_pct,
                        "source": "ibkr_delayed" if is_delayed else "ibkr",
                    }
        except Exception as e:
            # This was logged at debug level, but LOG_LEVEL=INFO in production means
            # the actual failure reason is silently discarded -- only the (equally
            # uninformative) "fetching last historical close" fallback line survives.
            # jarvis-engine-data-integrity-watch has been flagging this exact fallback
            # firing repeatedly for MES with zero visibility into why. Bump to warning
            # so the real exception is captured on the next occurrence.
            logger.warning(
                f"IBKR reqTickersAsync failed for {symbol} (will try historical fallback): {e}"
            )

        # Fallback: use last historical bar close (works even without L1 subscription)
        try:
            logger.info(f"IBKR snapshot fallback: fetching last historical close for {symbol}")
            bars_df = await asyncio.wait_for(
                self.get_historical_bars(
                    symbol, duration="1 D", bar_size="1 hour", is_futures=is_futures
                ),
                timeout=_IBKR_DATA_REQUEST_TIMEOUT_S,
            )
            if not bars_df.empty and "close" in bars_df.columns:
                last_close = float(bars_df.iloc[-1]["close"])
                prev_close = float(bars_df.iloc[-2]["close"]) if len(bars_df) >= 2 else None
                change_pct = ((last_close - prev_close) / prev_close * 100) if prev_close else None
                logger.info(f"IBKR historical fallback price for {symbol}: {last_close}")
                return {
                    "last_price": last_close,
                    "prev_close": prev_close,
                    "change_pct": change_pct,
                    "source": "ibkr_historical",
                }
        except Exception as e2:
            logger.warning(f"IBKR historical fallback also failed for {symbol}: {e2}")

        return {
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
            "source": "ibkr_error",
        }

    async def subscribe_real_time(
        self,
        symbol: str,
        callback: Callable[[MarketDataBar], None],
        is_futures: bool = False,
    ):
        """Subscribe to real-time 5-second streaming bars."""
        if not self._connected:
            logger.error("Not connected to IBKR")
            return
        # Record the sub so it can be replayed if a reconnect rebuilds the IB client.
        self._realtime_subs = [s for s in self._realtime_subs if s[0] != symbol]
        self._realtime_subs.append((symbol, callback, is_futures))
        try:
            contract = await self._qualified_contract(symbol, is_futures)
            bars = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
            bars.updateEvent += lambda bars, hasNewBar: (
                callback(
                    MarketDataBar(
                        symbol=symbol,
                        timestamp=datetime.fromtimestamp(bars[-1].time),
                        open=bars[-1].open_,
                        high=bars[-1].high,
                        low=bars[-1].low,
                        close=bars[-1].close,
                        volume=bars[-1].volume,
                        source="IBKR",
                    )
                )
                if hasNewBar
                else None
            )
        except Exception as e:
            logger.warning(f"IBKR subscribe_real_time failed for {symbol}: {e}")

    @property
    def is_connected(self) -> bool:
        # Consult the live socket, not just the cached flag. ib_async.IB.isConnected()
        # is a local socket-state check (no network round-trip), so this stays cheap
        # on the hot path (get_bars / get_current_price read it on every call).
        if not self._connected or self._ib is None:
            return False
        try:
            return bool(self._ib.isConnected())
        except Exception:
            return False

    def _on_disconnected(self) -> None:
        """ib_async disconnectedEvent handler — flip the flag the moment IB drops."""
        if self._connected:
            logger.warning("IBKR data leg disconnected (event) — marking offline")
        self._connected = False

    async def resubscribe_all(self) -> None:
        """Replay real-time bar subscriptions after a reconnect. No-op today
        (nothing calls subscribe_real_time), but keeps a future feed alive."""
        subs = list(self._realtime_subs)
        self._realtime_subs = []
        for symbol, callback, is_futures in subs:
            try:
                await self.subscribe_real_time(symbol, callback, is_futures)
            except Exception as e:
                logger.warning(f"IBKR resubscribe failed for {symbol}: {e}")

    async def get_executions(self) -> list[dict]:
        """
        Return recent IB execution fills via reqExecutionsAsync().
        Same schema as IBGatewayManager.get_executions() so IBKRReconciler
        can use either connector interchangeably.
        """
        if not self._ib or not self._connected:
            return []
        try:
            fills = await self._ib.reqExecutionsAsync()
            result = []
            for fill in fills:
                contract = fill.contract
                execution = fill.execution
                commission_report = fill.commissionReport
                result.append(
                    {
                        "exec_id": execution.execId,
                        "account": execution.acctNumber,
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "expiry": getattr(contract, "lastTradeDateOrContractMonth", ""),
                        "side": execution.side,
                        "quantity": execution.shares,
                        "price": execution.price,
                        "avg_price": execution.avgPrice,
                        "commission": getattr(commission_report, "commission", None),
                        "exchange": execution.exchange,
                        "currency": contract.currency,
                        "fill_time": str(execution.time),
                        "order_id": execution.orderId,
                    }
                )
            return result
        except Exception as exc:
            logger.warning("IBKRDataConnector.get_executions failed: %s", exc)
            return []

    async def get_positions(self) -> list[dict]:
        """
        Return current IB positions as a list of dicts. Same schema as
        IBGatewayManager.get_positions() (engine/execution/ib_gateway.py) so
        GET /brokers/positions can use either connector interchangeably.

        Positions are account-level in IB, not per-clientId, so this data-leg
        connection sees the same account state as the order-leg connection --
        added 2026-08-11 (#608 follow-up) because this connector previously
        had no position-query method at all, silently masking that gap behind
        a broad try/except in the router.
        """
        if not self._ib or not self._connected:
            return []
        try:
            positions = await self._ib.reqPositionsAsync()
        except Exception as exc:
            logger.error("IBKRDataConnector.get_positions: reqPositionsAsync failed: %s", exc)
            positions = []

        # Cross-check against ib_async's continuously-updated position cache,
        # same reqPositionsAsync-can-return-empty hardening as
        # IBGatewayManager.get_positions() (2026-08-03 incident).
        try:
            cached = self._ib.positions()
        except Exception:
            cached = []
        if not positions and cached:
            logger.error(
                "IBKRDataConnector.get_positions: reqPositionsAsync returned EMPTY but "
                "the position cache holds %d entries — using the cache instead.",
                len(cached),
            )
            positions = cached

        try:
            result = []
            for pos in positions:
                contract = pos.contract
                result.append(
                    {
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "exchange": getattr(contract, "exchange", ""),
                        "currency": contract.currency,
                        "position": pos.position,
                        "avg_cost": pos.avgCost,
                        "market_price": None,
                        "market_value": None,
                        "unrealized_pnl": None,
                        "account": pos.account,
                    }
                )
            return result
        except Exception as exc:
            logger.error("IBKRDataConnector.get_positions failed: %s", exc, exc_info=True)
            return []

    async def health_check(self) -> dict:
        """Round-trip verify the data leg rather than trusting the shallow
        `_connected` flag alone -- `_connected` only reflects a local socket
        state and stayed True for hours during the 2026-08-15 wedge incident
        (Gateway socket open, API dead). A bounded `reqCurrentTimeAsync()`
        probe, same pattern as the execution connector's health_check, is the
        only way to tell "socket open" from "API actually answering"."""
        verified = False
        latency_ms: float | None = None
        if self._connected and self._ib is not None:
            try:
                t0 = time.monotonic()
                await asyncio.wait_for(
                    self._ib.reqCurrentTimeAsync(), timeout=_IBKR_DATA_REQUEST_TIMEOUT_S
                )
                latency_ms = (time.monotonic() - t0) * 1000
                verified = True
            except Exception:
                verified = False

        if verified:
            status = "connected"
        elif self._connected:
            status = "wedged"
        else:
            status = "disconnected"

        return {
            "status": status,
            "connected": verified,
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "mode": "live" if self._port == 4001 else "paper",
            "port": self._port,
            "host": self._host,
            "client_id": self._client_id,
        }


class PolygonDataConnector:
    """
    Polygon.io market data — historical OHLCV bars and price snapshots.
    Requires POLYGON_API_KEY in .env. Free tier: 5 API calls/min.
    """

    # Class-level rate limiter shared across all instances
    _call_timestamps: list[float] = []
    _RATE_LIMIT = 4  # conservative (free tier = 5/min)
    _RATE_WINDOW = 60.0
    # Simple sync cache: {key: {"data": ..., "ts": float}}
    _cache: dict[str, dict] = {}
    _CACHE_TTL = 60.0

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def _check_rate_limit(self) -> bool:
        """Return True if we can make a call. Logs and returns False if throttled."""
        now = time.time()
        self._call_timestamps[:] = [t for t in self._call_timestamps if now - t < self._RATE_WINDOW]
        if len(self._call_timestamps) >= self._RATE_LIMIT:
            wait = self._RATE_WINDOW - (now - self._call_timestamps[0])
            logger.warning(
                f"[polygon] Rate guard: {len(self._call_timestamps)} calls in 60s, next slot in {wait:.0f}s"
            )
            return False
        self._call_timestamps.append(now)
        return True

    def _cache_get(self, key: str) -> dict | None:
        """Return cached data if within TTL, else None."""
        entry = self._cache.get(key)
        if entry and (time.time() - entry["ts"]) < self._CACHE_TTL:
            return entry["data"]
        return None

    def _cache_get_expired(self, key: str) -> dict | None:
        """Return cached data even if expired (429 fallback)."""
        entry = self._cache.get(key)
        return entry["data"] if entry else None

    def _cache_set(self, key: str, data) -> None:
        self._cache[key] = {"data": data, "ts": time.time()}

    def connect(self):
        try:
            from polygon import RESTClient

            self._client = RESTClient(self._api_key)
            logger.info("Polygon.io connected")
        except ImportError:
            logger.warning("polygon-api-client not installed. Run: pip install polygon-api-client")

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def get_historical_bars(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        timespan: str = "minute",
        multiplier: int = 5,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars. timespan: minute/hour/day. multiplier: 1/5/15/60."""
        if not self._client:
            return pd.DataFrame()

        cache_key = f"bars:{symbol}:{multiplier}:{timespan}:{from_date}:{to_date}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if not self._check_rate_limit():
            expired = self._cache_get_expired(cache_key)
            if expired is not None:
                logger.info(f"[polygon] Returning expired cache for {symbol} bars (rate limited)")
                return expired
            return pd.DataFrame()

        bars = []
        try:
            for agg in self._client.list_aggs(
                symbol, multiplier, timespan, from_date, to_date, limit=50000
            ):
                bars.append(
                    {
                        "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                        "open": agg.open,
                        "high": agg.high,
                        "low": agg.low,
                        "close": agg.close,
                        "volume": agg.volume,
                    }
                )
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "too many" in error_str:
                logger.warning(
                    f"[polygon] 429 rate limit for {symbol} bars — returning expired cache"
                )
                expired = self._cache_get_expired(cache_key)
                return expired if expired is not None else pd.DataFrame()
            logger.warning(f"Polygon get_historical_bars failed for {symbol}: {e}")
            return pd.DataFrame()
        result = pd.DataFrame(bars)
        if not result.empty:
            self._cache_set(cache_key, result)
        return result

    def get_last_price(self, symbol: str) -> dict:
        """Get latest price via most recent 1-minute bar. Works for equities and futures."""
        if not self._client:
            return {
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "polygon_unavailable",
            }

        cache_key = f"price:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return {**cached, "source": "polygon_cache"}

        if not self._check_rate_limit():
            expired = self._cache_get_expired(cache_key)
            if expired:
                return {**expired, "source": "polygon_cache_expired"}
            return {
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "polygon_rate_limited",
            }

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

            recent_bars = list(
                self._client.list_aggs(symbol, 1, "minute", two_days_ago, today, limit=10)
            )
            if not recent_bars:
                return {
                    "last_price": None,
                    "prev_close": None,
                    "change_pct": None,
                    "source": "polygon_empty",
                }

            last_price = float(recent_bars[-1].close)
            prev_bars = list(
                self._client.list_aggs(symbol, 1, "day", three_days_ago, two_days_ago, limit=2)
            )
            prev_close = float(prev_bars[-1].close) if prev_bars else None
            change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close else None

            result = {
                "last_price": last_price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "source": "polygon",
            }
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "too many" in error_str:
                logger.warning(
                    f"[polygon] 429 rate limit for {symbol} price — returning expired cache"
                )
                expired = self._cache_get_expired(cache_key)
                if expired:
                    return {**expired, "source": "polygon_cache_expired"}
                return {
                    "last_price": None,
                    "prev_close": None,
                    "change_pct": None,
                    "source": "polygon_rate_limited",
                }
            logger.warning(f"Polygon get_last_price failed for {symbol}: {e}")
            return {
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "polygon_error",
            }

    def get_vix_value(self) -> dict:
        """Get VIX index value. Polygon indices use 'I:VIX' ticker."""
        if not self._client:
            return {"value": None, "source": "polygon_unavailable"}
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            bars = list(self._client.list_aggs("I:VIX", 1, "day", yesterday, today, limit=2))
            if bars:
                return {"value": float(bars[-1].close), "source": "polygon"}
        except Exception as e:
            logger.warning(f"Polygon get_vix_value failed: {e}")
        return {"value": None, "source": "polygon_error"}

    def get_options_expirations(self, symbol: str) -> list:
        """List available options expiration dates for an underlying symbol."""
        if not self._client:
            return []
        try:
            contracts = self._client.list_options_contracts(symbol, limit=500)
            expirations = sorted(
                {c.expiration_date for c in contracts if hasattr(c, "expiration_date")}
            )
            return expirations
        except Exception as e:
            logger.warning(f"Polygon get_options_expirations failed for {symbol}: {e}")
            return []


class FinnhubConnector:
    """Finnhub for news and sentiment. Free tier: 60 calls/min."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def connect(self):
        try:
            import finnhub

            self._client = finnhub.Client(api_key=self._api_key)
            logger.info("Finnhub connected")
        except ImportError:
            logger.warning("finnhub-python not installed. Run: pip install finnhub-python")

    def get_news_sentiment(self, symbol: str) -> dict:
        if not self._client:
            return {}
        try:
            return self._client.news_sentiment(symbol)
        except Exception as e:
            logger.error(f"Finnhub sentiment error for {symbol}: {e}")
            return {}

    def get_company_news(self, symbol: str, from_date: str, to_date: str) -> list:
        if not self._client:
            return []
        try:
            return self._client.company_news(symbol, _from=from_date, to=to_date)
        except Exception as e:
            logger.error(f"Finnhub news error for {symbol}: {e}")
            return []


class RedditSentimentConnector:
    """Reddit sentiment via ApeWisdom API (free, no auth)."""

    APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"

    async def get_trending_tickers(self, filter_name: str = "all-stocks") -> list:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                url = self.APEWISDOM_URL.format(filter=filter_name, page=1)
                resp = await client.get(url, timeout=10)
                return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"ApeWisdom error: {e}")
            return []


class MarketDataManager:
    """
    Unified market data access for all agents.
    Waterfall: IBKR → Polygon → CSV cache → structured None (no silent zeros).
    """

    # Single source of truth for all futures mappings
    FUTURES_MAP = FUTURES_MAP

    def __init__(self, config):
        self._config = config
        self.ibkr: Optional[IBKRDataConnector] = None
        self.schwab: Optional["SchwabConnector"] = None
        self.polygon: Optional[PolygonDataConnector] = None
        self.polygon_streamer: Optional[PolygonStreamer] = None
        self.finnhub: Optional[FinnhubConnector] = None
        self.reddit = RedditSentimentConnector()
        # Serialize IBKR reconnects so the watchdog and a manual POST /data/reconnect
        # never rebuild two IB() sockets on the same (data-leg) clientId concurrently.
        self._ibkr_lock = asyncio.Lock()
        # Observability: which data tier last served, and when IBKR last gave data —
        # surfaced in /health/full so degrade is never silent.
        self._last_bar_source: Optional[str] = None
        self._last_price_source: Optional[str] = None
        self._last_ibkr_data_ts: Optional[float] = None
        # Per-symbol wall-clock timestamp of the last successful bar/price serve,
        # so /health/full can expose per-instrument staleness (not just the global
        # last source). Recorded at the public get_bars/get_current_price exits.
        self._symbol_last_ts: dict[str, float] = {}
        # Set by IBDataWatchdog.start() so /health/full can read its status.
        self._watchdog = None

    def inject_schwab(self, connector: "SchwabConnector") -> None:
        """Wire in a SchwabConnector at startup (called from main.py after Schwab connects)."""
        self.schwab = connector
        logger.info("MarketDataManager: SchwabConnector injected as Tier 2 data source")

    def _mark_symbol_fresh(self, symbol: str) -> None:
        """Record the wall-clock time we last served data for `symbol` (any tier).

        Powers /health/full per_symbol_freshness so per-instrument staleness is
        visible. Defensive and ~nanosecond cost — never raises into the hot path.
        """
        try:
            self._symbol_last_ts[symbol.upper()] = time.time()
        except Exception:
            pass

    def symbol_freshness(self) -> dict[str, float]:
        """Map of symbol -> seconds since data was last served for it.

        Read by /health/full. Cheap, defensive, and snapshot-consistent (one
        `now` for the whole map).
        """
        now = time.time()
        out: dict[str, float] = {}
        for sym, ts in list(self._symbol_last_ts.items()):
            try:
                out[sym] = round(now - ts, 1)
            except Exception:
                continue
        return out

    async def initialize(self):
        """Connect to all available data sources."""
        self.ibkr = IBKRDataConnector(
            host=self._config.IBKR_HOST,
            port=self._config.IBKR_PORT,
            client_id=resolve_data_client_id(self._config),
            connect_timeout=max(30.0, getattr(self._config, "IBKR_CONNECT_TIMEOUT_SECONDS", 30.0)),
        )
        ibkr_connected = await self.ibkr.connect()
        if not ibkr_connected:
            logger.warning(
                "IBKR not connected — start IB Gateway (port 4002 paper, 4001 live). "
                "Data will fall back to Polygon."
            )

        if self._config.POLYGON_API_KEY:
            self.polygon = PolygonDataConnector(self._config.POLYGON_API_KEY)
            self.polygon.connect()

            # Tier 2.5: Real-time stream (requires Polygon plan with WebSocket access)
            if getattr(self._config, "POLYGON_STREAM_ENABLED", True):
                watchlist = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "MSFT", "AMD", "META"]
                self.polygon_streamer = PolygonStreamer(self._config.POLYGON_API_KEY, watchlist)
                # Connection is started by main.py in the background
        else:
            logger.warning("POLYGON_API_KEY not set — set it in .env for price data fallback.")

        if self._config.FINNHUB_API_KEY:
            self.finnhub = FinnhubConnector(self._config.FINNHUB_API_KEY)
            self.finnhub.connect()

        logger.info(
            f"Market data initialized: IBKR={'connected' if ibkr_connected else 'offline'}, "
            f"Polygon={'connected' if self.polygon else 'not configured'}"
        )

    async def reconnect_ibkr(self, timeout: float = 15.0) -> bool:
        """Idempotent IBKR data-leg reconnect, safe under concurrent callers.

        Shared by the IBDataWatchdog and POST /data/reconnect. The lock guarantees
        only one rebuild happens at a time, so two IB() sockets never race on the
        same data-leg clientId.
        """
        async with self._ibkr_lock:
            if self.ibkr is not None and self.ibkr.is_connected:
                return True
            if self.ibkr is not None:
                try:
                    await self.ibkr.disconnect()
                except Exception:
                    pass
            self.ibkr = IBKRDataConnector(
                host=self._config.IBKR_HOST,
                port=self._config.IBKR_PORT,
                client_id=resolve_data_client_id(self._config),
                connect_timeout=max(
                    getattr(self._config, "IBKR_CONNECT_TIMEOUT_SECONDS", 5.0), timeout
                ),
            )
            ok = await self.ibkr.connect()
            if ok:
                try:
                    await self.ibkr.resubscribe_all()
                except Exception as e:
                    logger.warning(f"IBKR resubscribe after reconnect failed: {e}")
            return ok

    async def get_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """
        Get OHLCV bars. Waterfall: TradingView MCP → IBKR → Polygon → CSV cache.
        Returns empty DataFrame if all sources unavailable.

        Thin public wrapper over ``_get_bars_impl`` that records per-symbol
        freshness on any non-empty serve (powers /health/full per_symbol_freshness).
        The waterfall + source-tracking logic is unchanged in the impl.
        """
        df = await self._get_bars_impl(symbol, lookback_days, timeframe, is_futures)
        try:
            if df is not None and not df.empty:
                self._mark_symbol_fresh(symbol)
        except Exception:
            pass
        return df

    async def _get_bars_impl(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """
        Get OHLCV bars. Waterfall: TradingView MCP → IBKR → Polygon → CSV cache.
        Returns empty DataFrame if all sources unavailable.

        TV MCP added 2026-04-21 (roadmap P0.2) as Tier 0 — fastest path to fresh
        bars. Requires TV Desktop running with --remote-debugging-port=9222.
        Preserves user's chart state via save/restore inside the fetcher.
        """
        is_futures = is_futures or symbol.upper() in FUTURES_MAP

        # Tier 0: TradingView MCP (live bars via CDP)
        if _tv_feed is not None and _tv_feed.is_available():
            tv_df = _tv_feed.get_bars(symbol, timeframe=timeframe, limit=300)
            if not tv_df.empty and "timestamp" in tv_df.columns:
                last_ts = pd.to_datetime(tv_df["timestamp"].iloc[-1], utc=True)
                age_hours = (datetime.now(last_ts.tzinfo) - last_ts).total_seconds() / 3600
                if age_hours <= 72:  # allow long weekends; caller checks tighter freshness
                    logger.info(
                        f"TV returned {len(tv_df)} bars for {symbol} "
                        f"({timeframe}, last bar {age_hours:.1f}h old)"
                    )
                    if _save_bars is not None:
                        _save_bars(tv_df, symbol, timeframe, "tv")
                    return tv_df
                logger.warning(
                    f"[{symbol}] TV returned stale bars ({age_hours:.1f}h old) — falling through"
                )

        # Tier 1: IBKR
        if self.ibkr and self.ibkr.is_connected:
            # GT-22 fix (2026-07-27): the map used to top out at 365 days -> "1 Y",
            # and `next(..., "1 M")` silently fell back to a 1-MONTH request for any
            # lookback_days beyond that (e.g. /regime/vix-percentile's default
            # lookback=252 + momentum_window=63 needs ~514 calendar days, so it was
            # quietly served ~21 daily bars instead of the ~252 its own label
            # claimed). Extended to 5 Y so multi-year daily-bar requests actually
            # fetch what they ask for; IBKR's reqHistoricalDataAsync accepts "N Y"
            # duration strings natively for daily bars.
            duration_map = [
                (1, "1 D"),
                (7, "1 W"),
                (30, "1 M"),
                (90, "3 M"),
                (180, "6 M"),
                (365, "1 Y"),
                (730, "2 Y"),
                (1095, "3 Y"),
                (1825, "5 Y"),
            ]
            duration = next((v for k, v in duration_map if lookback_days <= k), "5 Y")
            bar_size_map = {
                "1m": "1 min",
                "5m": "5 mins",
                "15m": "15 mins",
                "1h": "1 hour",
                "4h": "4 hours",
                "1d": "1 day",
            }
            bar_size = bar_size_map.get(timeframe, "5 mins")
            df = await self.ibkr.get_historical_bars(symbol, duration, bar_size, is_futures)
            if not df.empty:
                logger.info(f"IBKR returned {len(df)} bars for {symbol}")
                df.attrs["source"] = "ibkr"
                df.attrs["symbol"] = symbol
                self._last_bar_source = "ibkr"
                self._record_ibkr_freshness()
                if _save_bars is not None:
                    _save_bars(df, symbol, timeframe, "ibkr")
                return df

        # Tier 1.5: SQLite bars cache — warm cache from previously-fetched IBKR data.
        # Fills the gap when IBKR is connected but reqHistoricalDataAsync returns
        # empty (e.g. weekend/holiday API behaviour). Tolerates up to 72h staleness
        # so Friday-close data survives through a full weekend.
        if _load_bars is not None:
            try:
                cached_df = _load_bars(symbol, timeframe)
                if not cached_df.empty and "timestamp" in cached_df.columns:
                    last_ts = pd.to_datetime(cached_df["timestamp"]).max()
                    if last_ts.tzinfo is not None:
                        age_hours = (datetime.now(last_ts.tzinfo) - last_ts).total_seconds() / 3600
                    else:
                        age_hours = (datetime.utcnow() - last_ts).total_seconds() / 3600
                    if age_hours <= 72:
                        bars_per_day = {
                            "1m": 390,
                            "5m": 78,
                            "15m": 26,
                            "1h": 24,
                            "4h": 6,
                            "1d": 1,
                        }.get(timeframe, 24)
                        n_bars = lookback_days * bars_per_day
                        cached_df = cached_df.tail(n_bars).copy()
                        logger.info(
                            f"SQLite cache returned {len(cached_df)} bars for {symbol} "
                            f"(last bar {age_hours:.1f}h ago)"
                        )
                        cached_df.attrs["source"] = "sqlite_cache"
                        cached_df.attrs["symbol"] = symbol
                        self._last_bar_source = "sqlite_cache"
                        return cached_df
                    logger.debug(
                        f"[{symbol}] SQLite cache stale ({age_hours:.1f}h) — falling through"
                    )
            except Exception as _exc:
                logger.debug(f"[{symbol}] SQLite cache load failed: {_exc}")

        # Tier 2: Polygon — SKIPPED for futures (Polygon free plan returns
        # the wrong asset, e.g. `CL` = Colgate-Palmolive stock, not crude oil).
        # See POLYGON_FUTURES_BLOCKLIST docstring for incident details.
        if self.polygon and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
            tf_map = {
                "1m": ("minute", 1),
                "5m": ("minute", 5),
                "15m": ("minute", 15),
                "1h": ("hour", 1),
                "4h": ("hour", 4),
                "1d": ("day", 1),
            }
            timespan, multiplier = tf_map.get(timeframe, ("minute", 5))
            polygon_symbol = POLYGON_FUTURES_MAP.get(symbol.upper(), symbol)
            df = self.polygon.get_historical_bars(
                polygon_symbol, from_date, to_date, timespan, multiplier
            )
            if not df.empty:
                logger.info(f"Polygon returned {len(df)} bars for {symbol}")
                df.attrs["source"] = "polygon"
                df.attrs["symbol"] = symbol
                self._last_bar_source = "polygon"
                if _save_bars is not None:
                    _save_bars(df, symbol, timeframe, "polygon")
                return df
            logger.warning(f"Polygon returned no data for {symbol} ({timespan}/{multiplier})")
        elif self.polygon and symbol.upper() in POLYGON_FUTURES_BLOCKLIST:
            logger.debug(
                f"[market_data] Polygon SKIPPED for {symbol} (futures — see incident 2026-04-16)"
            )

        # Tier 3: CSV backtest cache — staleness guard: reject if last bar > 2 days old
        df = self._load_csv_cache(symbol, timeframe, lookback_days)
        if not df.empty:
            if "timestamp" in df.columns:
                last_ts = pd.to_datetime(df["timestamp"].iloc[-1])
                staleness_days = (datetime.now() - last_ts.replace(tzinfo=None)).days
                if staleness_days > 2:
                    logger.warning(
                        f"[{symbol}] CSV cache for {timeframe} is {staleness_days}d stale "
                        f"(last bar: {last_ts.date()}) — skipping to avoid stale signal contamination"
                    )
                    df = pd.DataFrame()
            if not df.empty:
                df.attrs["source"] = "csv_cache"
                df.attrs["symbol"] = symbol
                self._last_bar_source = "csv_cache"
                return df

        logger.error(
            f"All data sources failed for {symbol} — IBKR offline and Polygon unavailable."
        )
        empty = pd.DataFrame()
        empty.attrs["source"] = "none"
        empty.attrs["symbol"] = symbol
        self._last_bar_source = "none"
        return empty

    def _record_ibkr_freshness(self) -> None:
        """Mark that IBKR just served fresh data.

        Updates the in-process timestamp IBDataWatchdog reads for staleness AND
        publishes a Redis ``datasource:ib_gateway:last_update`` heartbeat so
        ``/system/data-integrity`` (and the real-money-readiness ``feeds_live``
        gate) can see the live IB feed. Until now only the TV Desktop scraper
        wrote a ``datasource:*:last_update`` key, so the integrity panel showed
        nothing but stale TV entries even while IB served live prices. The
        timestamp value is a timezone-aware UTC ISO string because the
        data-integrity endpoint does ``fromisoformat`` then subtracts from an
        aware ``now`` -- a naive string would raise and be silently skipped.
        Best-effort: a Redis failure must never break the price/bar hot path.
        """
        self._last_ibkr_data_ts = time.time()
        try:
            import redis

            r = redis.Redis(
                host="localhost",
                port=6379,
                db=0,
                decode_responses=True,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
            r.set(
                "datasource:ib_gateway:last_update",
                datetime.now(timezone.utc).isoformat(),
            )
        except Exception as _hb_err:  # noqa: BLE001 - heartbeat is best-effort
            logger.debug(f"[ib-freshness] Redis heartbeat write failed: {_hb_err}")

    async def get_current_price(self, symbol: str, is_futures: bool = False) -> dict:
        """
        Get latest price. Returns {last_price, prev_close, change_pct, source}.
        Never returns silent 0.0 — None means genuinely unavailable.

        Thin public wrapper over ``_get_current_price_impl`` that records per-symbol
        freshness whenever a real price is served (powers /health/full
        per_symbol_freshness). Waterfall logic is unchanged in the impl.
        """
        result = await self._get_current_price_impl(symbol, is_futures)
        try:
            if isinstance(result, dict) and result.get("last_price") is not None:
                self._mark_symbol_fresh(symbol)
        except Exception:
            pass
        return result

    async def get_current_price_envelope(
        self, symbol: str, is_futures: bool = False, stale_after_s: Optional[float] = None
    ) -> dict:
        """Provenance-aware wrapper over ``get_current_price`` (Phase 1, additive).

        Returns the canonical DataEnvelope shape
        ``{value, source, as_of, is_live, stale_after_s}`` WITHOUT altering the
        underlying waterfall or the plain ``get_current_price`` contract. ``is_live``
        is derived from the serving tier + per-symbol freshness + the IBKR data-leg
        connection — never hardcoded. Existing callers are unaffected.
        """
        result = await self.get_current_price(symbol, is_futures)
        env = build_envelope(
            value=result.get("last_price"),
            source=result.get("source"),
            as_of=self._symbol_last_ts.get(symbol.upper()),
            stale_after_s=(
                DEFAULT_STALE_AFTER_S if stale_after_s is None else float(stale_after_s)
            ),
            ibkr_data_connected=bool(self.ibkr and self.ibkr.is_connected),
            now=time.time(),
        )
        return env.to_dict()

    async def _get_current_price_impl(self, symbol: str, is_futures: bool = False) -> dict:
        """
        Get latest price. Returns {last_price, prev_close, change_pct, source}.
        Never returns silent 0.0 — None means genuinely unavailable.
        """
        is_futures = is_futures or symbol.upper() in FUTURES_MAP

        # Tier 1: IBKR
        if self.ibkr and self.ibkr.is_connected:
            result = await self.ibkr.get_snapshot_price(symbol, is_futures)
            if result.get("last_price"):
                self._last_price_source = "ibkr"
                self._record_ibkr_freshness()
                return result

        # Tier 2: Schwab (real-time quotes, no historical bars)
        if self.schwab is not None and self.schwab.is_connected:
            try:
                schwab_sym = SCHWAB_FUTURES_MAP.get(symbol.upper(), symbol)
                quotes = await self.schwab.get_quotes([schwab_sym])
                quote = quotes.get(schwab_sym) or quotes.get(symbol)
                if quote:
                    price = quote.get("last") or quote.get("mark")
                    if price:
                        change_pct = quote.get("change_pct")
                        logger.info(f"Schwab Tier 2 price for {symbol} ({schwab_sym}): {price}")
                        return {
                            "last_price": float(price),
                            "prev_close": None,
                            "change_pct": float(change_pct) if change_pct is not None else None,
                            "source": "schwab",
                        }
            except Exception as _schwab_err:
                logger.debug(f"Schwab Tier 2 failed for {symbol}: {_schwab_err}")
        elif self.schwab is not None and not self.schwab.is_connected:
            logger.debug(f"Schwab not connected — skipping Tier 2 for {symbol}")

        # Tier 2.5: TradingView Desktop (optional — only when CDP connected)
        if _tv_feed is not None and _tv_feed.is_available():
            try:
                # Map micro futures to TradingView continuous contract symbols
                tv_symbol_map = {
                    "MCL": "MCL1!",
                    "MNQ": "MNQ1!",
                    "MES": "MES1!",
                    "MGC": "MGC1!",
                    "CL": "CL1!",
                    "NQ": "NQ1!",
                    "ES": "ES1!",
                    "GC": "GC1!",
                }
                tv_symbol = tv_symbol_map.get(symbol.upper(), symbol)
                quote = _tv_feed.get_quote(tv_symbol)
                if quote and quote.get("close"):
                    logger.info(f"TradingView Tier 2.5 price for {symbol}: {quote['close']}")
                    return {
                        "last_price": float(quote["close"]),
                        "prev_close": None,
                        "change_pct": None,
                        "source": "tradingview",
                    }
            except Exception as _tv_err:
                logger.debug(f"TradingView Tier 2.5 failed for {symbol}: {_tv_err}")

        # Tier 3: Polygon Stream Cache (Fastest Tier 2 fallback)
        if self.polygon_streamer and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            stream_bar = self.polygon_streamer.get_latest_bar(symbol.upper())
            if stream_bar and stream_bar.get("close"):
                logger.info(f"Polygon Stream Tier 3 price for {symbol}: {stream_bar['close']}")
                return {
                    "last_price": float(stream_bar["close"]),
                    "prev_close": None,
                    "change_pct": None,
                    "source": "polygon_stream",
                }

        # Tier 4: Polygon REST — SKIPPED for futures (returns wrong asset on free plan).
        # See POLYGON_FUTURES_BLOCKLIST. Stocks/ETFs still flow through.
        if self.polygon and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            polygon_symbol = POLYGON_FUTURES_MAP.get(symbol.upper(), symbol)
            result = self.polygon.get_last_price(polygon_symbol)
            if result.get("last_price"):
                return result
        elif self.polygon and symbol.upper() in POLYGON_FUTURES_BLOCKLIST:
            logger.debug(
                f"[market_data] Polygon last_price SKIPPED for {symbol} "
                f"(futures — see incident 2026-04-16)"
            )

        # Tier 5: CSV cache last close
        df = self._load_csv_cache(symbol, "1d", 2)
        if not df.empty and "close" in df.columns:
            last_close = float(df.iloc[-1]["close"])
            return {
                "last_price": last_close,
                "prev_close": None,
                "change_pct": None,
                "source": "csv_cache",
            }

        return {"last_price": None, "prev_close": None, "change_pct": None, "source": "unavailable"}

    async def get_tick_price(self, symbol: str, is_futures: bool = False) -> dict:
        """
        Ticker-only price read — explicitly skips TradingView.

        Waterfall: IBKR snapshot → Schwab quote → Polygon → CSV cache.

        Rationale: TV Desktop via CDP is the right bar source (Tier 0 in
        get_bars) but for ticker-only reads it incurs a chart-switch cost
        that can balloon /portfolio/summary latency when called once per
        open position. This method guarantees the tick path never touches
        TV, keeping per-position reads to sub-200ms when IBKR/Schwab are up.
        """
        is_futures = is_futures or symbol.upper() in FUTURES_MAP

        # Tier 0: Redis Real-Time Fabric (Phase 2.1)
        #
        # GT-17 follow-up (2026-07-27): this tier used to trust whatever was
        # cached under market:latest:{symbol} unconditionally and forever —
        # _stream_to_redis() (tradingview_stream.py) SETs that key with no
        # TTL, and nothing here checked the sibling
        # datasource:ticks:{symbol}:last_update freshness marker it writes
        # alongside it. A stale or mislabeled TV pane (e.g. a chart that
        # hadn't finished switching symbols) could poison a symbol's entry
        # and it would be served to /watchlist indefinitely — completely
        # bypassing Tier 1 IBKR (and the qualified-contract fix above) since
        # this tier returns first. That mechanism, not the Tier-1 contract
        # hash collision, matches the originally-reported symptom: a wrong
        # last_price *and* change_pct=null (this tier hardcodes change_pct
        # to None; Tier 1's historical-bars fallback would have produced a
        # non-null change_pct). Now gated on freshness so a stale cache
        # entry falls through to Tier 1 instead of being trusted forever.
        try:
            import json

            import redis

            r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
            # Try symbol as-is and uppercase
            for sym_key in [symbol, symbol.upper()]:
                val = r.get(f"market:latest:{sym_key}")
                if val:
                    last_update_raw = r.get(f"datasource:ticks:{sym_key}:last_update")
                    if not last_update_raw:
                        logger.debug(
                            f"[get_tick_price] Redis fabric hit for {symbol} has no "
                            f"freshness marker — treating as stale, skipping"
                        )
                        continue
                    try:
                        last_update = datetime.fromisoformat(last_update_raw)
                        age_s = (
                            datetime.now(last_update.tzinfo) - last_update
                        ).total_seconds()
                    except (ValueError, TypeError) as _ts_err:
                        logger.debug(
                            f"[get_tick_price] Redis fabric freshness marker for "
                            f"{symbol} unparseable ({_ts_err}) — treating as stale"
                        )
                        continue
                    if age_s > DEFAULT_STALE_AFTER_S or age_s < 0:
                        logger.debug(
                            f"[get_tick_price] Redis fabric entry for {symbol} is "
                            f"{age_s:.0f}s old (> {DEFAULT_STALE_AFTER_S:.0f}s) — "
                            f"stale, falling through to Tier 1"
                        )
                        continue
                    data = json.loads(val)
                    if data.get("close"):
                        return {
                            "last_price": float(data["close"]),
                            "prev_close": float(data.get("open", 0.0)),
                            "change_pct": None,
                            "source": "redis_fabric",
                        }
        except Exception as _redis_err:
            logger.debug(f"[get_tick_price] Redis fetch failed for {symbol}: {_redis_err}")

        # Tier 1: IBKR snapshot (real-time L1, sub-100ms typical)
        if self.ibkr and self.ibkr.is_connected:
            result = await self.ibkr.get_snapshot_price(symbol, is_futures)
            if result.get("last_price"):
                self._last_price_source = "ibkr"
                self._record_ibkr_freshness()
                return result

        # Tier 2: Schwab quotes
        if self.schwab is not None and self.schwab.is_connected:
            try:
                schwab_sym = SCHWAB_FUTURES_MAP.get(symbol.upper(), symbol)
                quotes = await self.schwab.get_quotes([schwab_sym])
                quote = quotes.get(schwab_sym) or quotes.get(symbol)
                if quote:
                    price = quote.get("last") or quote.get("mark")
                    if price:
                        change_pct = quote.get("change_pct")
                        return {
                            "last_price": float(price),
                            "prev_close": None,
                            "change_pct": float(change_pct) if change_pct is not None else None,
                            "source": "schwab",
                        }
            except Exception as _schwab_err:
                logger.debug(f"[get_tick_price] Schwab failed for {symbol}: {_schwab_err}")

        # Tier 3: Polygon Stream Cache
        if self.polygon_streamer and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            stream_bar = self.polygon_streamer.get_latest_bar(symbol.upper())
            if stream_bar and stream_bar.get("close"):
                return {
                    "last_price": float(stream_bar["close"]),
                    "prev_close": None,
                    "change_pct": None,
                    "source": "polygon_stream",
                }

        # Tier 4: Polygon REST (stocks/ETFs only — futures blocklisted)
        if self.polygon and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            polygon_symbol = POLYGON_FUTURES_MAP.get(symbol.upper(), symbol)
            result = self.polygon.get_last_price(polygon_symbol)
            if result.get("last_price"):
                return result

        # Tier 5: CSV cache last close
        df = self._load_csv_cache(symbol, "1d", 2)
        if not df.empty and "close" in df.columns:
            last_close = float(df.iloc[-1]["close"])
            return {
                "last_price": last_close,
                "prev_close": None,
                "change_pct": None,
                "source": "csv_cache",
            }

        return {"last_price": None, "prev_close": None, "change_pct": None, "source": "unavailable"}

    async def get_batch_prices(self, symbols: list) -> dict:
        """
        Get current prices for multiple symbols in parallel.
        Uses get_tick_price to avoid TradingView high-latency chart switching.
        """
        if not symbols:
            return {}

        results = await asyncio.gather(
            *[self.get_tick_price(s) for s in symbols], return_exceptions=True
        )

        batch = {}
        for symbol, result in zip(symbols, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(f"[market_data] Batch price failed for {symbol}: {result}")
                batch[symbol] = {
                    "last_price": None,
                    "prev_close": None,
                    "change_pct": None,
                    "source": "error",
                }
            else:
                batch[symbol] = result

        return batch

    async def get_vix(self) -> dict:
        """
        Get VIX index value. Returns {value, source}.
        Waterfall: FRED → IBKR → Polygon.
        """
        # Tier 1: FRED (VIXCLS series — most reliable, free)
        try:
            from data.fred_data import FREDDataService

            fred = FREDDataService(getattr(self._config, "FRED_API_KEY", None))
            vix_val = await fred.get_latest_value("VIXCLS")
            if vix_val is not None:
                return {"value": float(vix_val), "source": "fred"}
        except Exception:
            pass

        # Tier 2: IBKR Index("VIX")
        if self.ibkr and self.ibkr.is_connected:
            result = await self.ibkr.get_snapshot_price("VIX", is_futures=False)
            if result.get("last_price"):
                return {"value": result["last_price"], "source": "ibkr"}

        # Tier 3: Polygon I:VIX
        if self.polygon:
            result = self.polygon.get_vix_value()
            if result.get("value"):
                return result

        return {"value": None, "source": "unavailable"}

    async def get_options_greeks(self, symbol: str) -> dict:
        """
        Get real-time Greeks for an option.
        Waterfall: IBKR → (Polygon unimplemented).
        """
        # Tier 1: IBKR
        if self.ibkr and self.ibkr.is_connected:
            return await self.ibkr.get_options_greeks(symbol)

        return {"error": "Options Greeks data source unavailable"}

    async def get_options_expirations(self, symbol: str) -> list:
        """
        Get available options expiration dates for a symbol.
        Waterfall: IBKR → Polygon.
        """
        # Tier 1: IBKR reqSecDefOptParams
        if self.ibkr and self.ibkr.is_connected:
            try:
                from ib_async import Stock

                contract = Stock(symbol, "SMART", "USD")
                chains = await self._ibkr_ib.reqSecDefOptParamsAsync(
                    "", "", contract.secType, contract.conId
                )
                if chains:
                    expirations = sorted(chains[0].expirations)
                    return list(expirations)
            except Exception as e:
                logger.warning(f"IBKR get_options_expirations failed for {symbol}: {e}")

        # Tier 2: Polygon
        if self.polygon:
            return self.polygon.get_options_expirations(symbol)

        return []

    def _load_csv_cache(self, symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
        """Load from CSV backtest cache as offline fallback."""
        try:
            cache_dir = Path(__file__).parent.parent / "backtest" / "cache"
            matches = sorted(cache_dir.glob(f"{symbol}_*_{timeframe}.csv"))
            if not matches:
                return pd.DataFrame()
            # Pick the file with the freshest DATA (latest end-date parsed from the
            # `{symbol}_{start}_{end}_{tf}.csv` name), not the lexicographically-last
            # filename. sorted()[-1] orders by START date, so an older-but-longer
            # slice could shadow a fresher one and serve wrong-era bars/prices.
            import re as _re

            def _end_date(p) -> str:
                m = _re.search(rf"_(\d{{4}}-\d{{2}}-\d{{2}})_{_re.escape(timeframe)}\.csv$", p.name)
                if m:
                    return m.group(1)
                dates = _re.findall(r"\d{4}-\d{2}-\d{2}", p.name)
                return dates[-1] if dates else ""

            chosen = max(matches, key=lambda p: (_end_date(p), p.name))
            df = pd.read_csv(chosen)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp")
            bars_per_day = {"1m": 390, "5m": 78, "15m": 26, "1h": 24, "4h": 6, "1d": 1}.get(
                timeframe, 24
            )
            df = df.tail(lookback_days * bars_per_day).copy()
            if not df.empty:
                logger.warning(f"[{symbol}] Using CSV cache: {chosen.name} ({len(df)} bars)")
            cols = [
                c
                for c in ["timestamp", "open", "high", "low", "close", "volume"]
                if c in df.columns
            ]
            return df[cols] if cols else pd.DataFrame()
        except Exception as e:
            logger.debug(f"[{symbol}] CSV cache load failed: {e}")
            return pd.DataFrame()
