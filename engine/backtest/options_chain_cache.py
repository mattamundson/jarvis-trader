"""
JARVIS TRADER — Historical Options Chain Cache (Polygon.io) [Strategy Novel #3 data layer]
==========================================================================================
Offline replay data for ``backtest/options_backtester.py``. Wires the scaffold's
``ChainProvider`` protocol to REAL historical SPY/QQQ options data from the
engine's existing Polygon.io subscription.

Why this module exists
----------------------
``options/chain_fetcher.py`` builds live chains but its ``fetch_chain`` currently
populates NO contracts (empty calls/puts) — there is no offline replay path. This
module is that path:

    signals -> PolygonChainCache.get_chain(symbol, as_of, target_dte)
             -> OptionsChain (real strikes, real historical prices, computed IV/Greeks)

Data source & tier reality (verified 2026-08-18 with the engine's key)
---------------------------------------------------------------------
* Reference contracts  (/v3/reference/options/contracts?as_of=...)  -> 200 OK
* Daily aggregates     (/v2/aggs/ticker/O:.../range/1/day/...)      -> 200 OK
* Options snapshot     (/v3/snapshot/options/...?as_of=...)         -> 403 NOT_AUTHORIZED
  (bid/ask/greeks snapshot product is a HIGHER Polygon tier than this key)

Consequences (honest, documented):
* Prices are DAILY bars (close / VWAP), not bid/ask snapshots. This module
  models bid/ask as ``mid * (1 ± relative_half_spread)`` so the scaffold's
  ``FlatSlippage`` keeps working with an explicit, single-place cost knob.
* IV is NOT provided by daily bars -> solved by Black-Scholes inversion from
  the daily close (bisection on ``options.premium_calculator.black_scholes_price``).
  SPY/QQQ are American-style but the early-exercise premium at <=45 DTE is small;
  the approximation is documented research-grade, not execution-grade.
* The tier's sustained rate limit is ~5 calls/min -> the cache fetches each
  contract's FULL daily series in ONE call (deduped across signals), paced.

Cache layout (parquet under ``<engine>/backtest/cache/options/``)
-----------------------------------------------------------------
* ``{SYMBOL}_daily.parquet``            — underlying daily bars (date, close, vwap)
* ``{SYMBOL}_{expiry}_universe.parquet`` — reference contract universe as-of (strike, type, ticker)
* ``{ticker}.parquet``                  — one file per option contract daily series
* ``manifest.json``                     — fetch provenance (symbol, window, api tier notes)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Reuse the existing data contract — DO NOT duplicate.
from options.chain_fetcher import OptionsChain, OptionsContract  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLYGON_REFERENCE = "https://api.polygon.io/v3/reference/options/contracts"
POLYGON_AGGS = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"

# Sustained rate limit observed on the engine's current Polygon tier (~5/min).
# Kept configurable so a tier upgrade (or a slower/faster plan) is a one-line change.
DEFAULT_REQUESTS_PER_MINUTE = 5.0
DEFAULT_RETRY_BACKOFF_S = 12.0

# Weekly expiry cadence for SPY/QQQ means the "nearest monthly >= target_dte" rule
# needs a deterministic monthly calendar: third Friday of each month.
MONTHLY_EXPIRY_WEEKDAY = 4  # Friday


def good_friday(year: int) -> date:
    """Good Friday via the Anonymous Gregorian algorithm (valid 1900-2099).

    When the third Friday of March/April IS Good Friday, monthly options
    expire the preceding Thursday (e.g. April 2025: 3rd Fri = 4/18 was
    Good Friday, so the monthly expired 4/17).
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    return easter - timedelta(days=2)  # Good Friday = Easter Sunday - 2 days


def _is_market_holiday(d: date) -> bool:
    """Exchange holidays that can fall on a monthly-expiry Friday (US equity
    options): Good Friday. Christmas/New Year never land on a 3rd Friday, and
    July 4th / Thanksgiving / MLK / Presidents / Memorial / Juneteenth fall on
    other weekdays. Kept as a single, explicit source of truth."""
    return d == good_friday(d.year)


def nth_weekday(year: int, month: int, n: int, weekday: int) -> date:
    """Return the ``n``-th ``weekday`` (0=Mon..6=Sun) of ``(year, month)``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = first + timedelta(days=offset + (n - 1) * 7)
    return day


def monthly_expiries(start: date, end: date) -> list[date]:
    """Monthly expiries in [start, end] (inclusive): 3rd Friday, pulled back to
    the preceding Thursday when that Friday is an exchange holiday."""
    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        exp = nth_weekday(y, m, 3, MONTHLY_EXPIRY_WEEKDAY)
        if _is_market_holiday(exp):
            exp = exp - timedelta(days=1)
        if exp >= start and exp <= end:
            out.append(exp)
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def next_monthly_expiry(as_of: date, min_dte: int) -> Optional[date]:
    """First monthly expiry with DTE >= ``min_dte`` counting from ``as_of``."""
    horizon = as_of + timedelta(days=min_dte + 40)
    for exp in monthly_expiries(as_of, horizon):
        if (exp - as_of).days >= min_dte:
            return exp
    return None


def option_ticker(symbol: str, expiry: date, opt_type: str, strike: float) -> str:
    """Polygon options ticker: O:{SYM}{YYMMDD}{C|P}{strike*1000:08d}."""
    if opt_type.lower() not in ("call", "put"):
        raise ValueError(f"opt_type must be 'call'/'put', got {opt_type!r}")
    leg = "C" if opt_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    return f"O:{symbol.upper()}{expiry.strftime('%y%m%d')}{leg}{strike_int:08d}"


# ---------------------------------------------------------------------------
# HTTP layer (injectable for tests)
# ---------------------------------------------------------------------------


def _to_date(value) -> date:
    """Normalize a date/Timestamp/str to a plain ``date`` (parquet round-trips
    store dates as pandas Timestamps)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    try:
        return value.date()  # pandas Timestamp etc.
    except AttributeError:
        return date.fromisoformat(str(value)[:10])


def _bar_date(ts_ms: int) -> date:
    """Polygon epoch-ms timestamps are UTC — convert in UTC so daily bars are
    never shifted a calendar day by the local timezone."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).date()


def _default_http_get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


@dataclass
class _RateLimiter:
    """Min-interval pacing for a sustained calls/min budget."""

    requests_per_minute: float

    def __post_init__(self):
        self._min_interval = 60.0 / max(self.requests_per_minute, 0.5)
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last = time.monotonic()


class PolygonClient:
    """Thin, testable wrapper over the Polygon REST endpoints we need."""

    def __init__(
        self,
        api_key: str,
        requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
        http_get: Optional[Callable[[str, str], dict]] = None,
    ):
        self._api_key = api_key
        self._limiter = _RateLimiter(requests_per_minute)
        self._http_get = http_get or _default_http_get

    def _get(self, url: str, retries: int = 3) -> dict:
        for attempt in range(retries):
            self._limiter.wait()
            try:
                return self._http_get(url, self._api_key)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < retries - 1:
                    logger.warning("[polygon] 429 on %s — backing off", url.split("?")[0])
                    time.sleep(DEFAULT_RETRY_BACKOFF_S * (attempt + 1))
                    continue
                if exc.code in (401, 403):
                    logger.error("[polygon] auth/tier error %s on %s", exc.code, url.split("?")[0])
                raise
        raise RuntimeError(f"polygon fetch failed after retries: {url}")

    # -- reference universe --------------------------------------------------

    def list_contracts(
        self,
        underlying: str,
        as_of: date,
        strike_min: Optional[float] = None,
        strike_max: Optional[float] = None,
    ) -> list[dict]:
        """Contracts for ``underlying`` as of ``as_of``, within a strike band.

        One (paginated) call. Returns raw dicts with strike_price/contract_type/
        expiration_date/ticker keys.
        """
        params = [
            f"underlying_ticker={underlying.upper()}",
            f"as_of={as_of.isoformat()}",
            "limit=1000",
        ]
        if strike_min is not None:
            params.append(f"strike_price.gte={strike_min}")
        if strike_max is not None:
            params.append(f"strike_price.lte={strike_max}")
        url = POLYGON_REFERENCE + "?" + "&".join(params)
        out: list[dict] = []
        while url:
            body = self._get(url)
            out.extend(body.get("results") or [])
            url = body.get("next_url")
            if url:  # next_url is absolute and carries its own auth
                url = url
        return out

    # -- daily aggregates ----------------------------------------------------

    def daily_bars(self, ticker: str, start: date, end: date) -> list[dict]:
        """Daily aggregate bars for a ticker (equity or option) in [start, end]."""
        url = POLYGON_AGGS.format(
            ticker=ticker, start=start.isoformat(), end=end.isoformat()
        )
        body = self._get(url)
        return body.get("results") or []


# ---------------------------------------------------------------------------
# IV solver (Black-Scholes inversion)
# ---------------------------------------------------------------------------


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    expiry: date,
    as_of: date,
    opt_type: str,
    risk_free_rate: float = 0.05,
    lo: float = 0.05,
    hi: float = 3.0,
    tol: float = 1e-4,
) -> float:
    """Solve IV by bisection on the engine's Black-Scholes price.

    Returns 0.0 when the price is outside the theoretical range (e.g. a stale
    print below intrinsic — common for far-OTM contracts in daily data).
    """
    from options.premium_calculator import black_scholes_price

    if price <= 0 or spot <= 0:
        return 0.0
    T = max((expiry - as_of).days, 1) / 365.0

    def bs(sigma: float) -> float:
        return black_scholes_price(spot, strike, T, risk_free_rate, sigma, opt_type)

    # Theoretical bounds: intrinsic value <= price <= spot (+0 for calls, K for puts)
    intrinsic = max(0.0, (spot - strike) if opt_type == "call" else (strike - spot))
    if price <= intrinsic + 1e-9:
        return 0.0
    if bs(hi) < price:
        return hi  # outside solver range -> cap (deep ITM, huge vol)

    for _ in range(80):  # bisection: 80 iterations shrinks (hi-lo) to ~1e-20
        mid = (lo + hi) / 2.0
        if bs(mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# The cache + chain provider
# ---------------------------------------------------------------------------


class PolygonChainCache:
    """Persistent historical options chain cache + ``ChainProvider`` adapter.

    Implements the scaffold's ``ChainProvider.get_chain(symbol, as_of, target_dte)``
    protocol so it can be passed straight to ``OptionsBacktester``.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
        requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
        http_get: Optional[Callable[[str, str], dict]] = None,
        relative_half_spread: float = 0.02,
        ladder_step_pct: float = 0.02,
        ladder_band_pct: float = 0.08,
        risk_free_rate: float = 0.05,
    ):
        if api_key is None:
            import os

            api_key = os.environ.get("POLYGON_API_KEY")
        if not api_key:
            raise ValueError(
                "PolygonChainCache needs POLYGON_API_KEY (pass api_key= or set env)"
            )
        if cache_dir is None:
            cache_dir = Path(__file__).resolve().parent / "cache" / "options"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = PolygonClient(
            api_key, requests_per_minute=requests_per_minute, http_get=http_get
        )
        self.relative_half_spread = relative_half_spread
        self.ladder_step_pct = ladder_step_pct
        self.ladder_band_pct = ladder_band_pct
        self.risk_free_rate = risk_free_rate

    # -- helpers -------------------------------------------------------------

    def _underlying_cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.upper()}_daily.parquet"

    def _universe_cache_path(self, symbol: str, expiry: date, as_of: date) -> Path:
        return self.cache_dir / f"{symbol.upper()}_{expiry:%Y-%m-%d}_{as_of:%Y-%m-%d}_universe.parquet"

    def _contract_cache_path(self, ticker: str) -> Path:
        # ticker like O:SPY250620C00580000 -> O_SPY250620C00580000.parquet
        safe = ticker.replace(":", "_")
        return self.cache_dir / f"{safe}.parquet"

    # -- underlying bars -----------------------------------------------------

    def get_underlying_bars(self, symbol: str, start: date, end: date) -> dict[date, dict]:
        """Daily bars for ``symbol`` in [start, end], cached. Returns {date: {close, vwap}}."""
        import pandas as pd

        symbol = symbol.upper()
        path = self._underlying_cache_path(symbol)
        df: Optional[pd.DataFrame] = None
        if path.exists():
            try:
                df = pd.read_parquet(path)
            except Exception as exc:
                logger.warning("[options_cache] unreadable %s: %s", path, exc)
        if df is None or df.empty or pd.to_datetime(df["date"]).max().date() < end - timedelta(days=7):
            bars = self.client.daily_bars(symbol, start, end)
            rows = [
                {
                    "date": _bar_date(b["t"]),
                    "close": float(b.get("c", 0.0)),
                    "vwap": float(b.get("vw", 0.0) or 0.0),
                }
                for b in bars
                if b.get("c") is not None
            ]
            df = pd.DataFrame(rows)
            df.to_parquet(path, index=False)
            logger.info("[options_cache] cached %d daily bars for %s", len(df), symbol)
        bars: dict[date, dict] = {}
        for _, row in df.iterrows():
            bars[_to_date(row["date"])] = {
                "close": float(row["close"]),
                "vwap": float(row.get("vwap", 0.0) or 0.0),
            }
        return bars

    # -- reference universe --------------------------------------------------

    def get_universe(
        self, symbol: str, expiry: date, as_of: date, strike_min: float, strike_max: float
    ) -> list[dict]:
        """Reference contracts for (symbol, expiry) as of ``as_of``, cached.

        The cache key includes ``as_of`` AND the caller passes a WIDE strike
        band (see ``get_chain``): a stale universe fetched for an earlier
        signal's narrow band would otherwise silently drop the current
        signal's strikes (observed with the 2025-03-13 vol-spike signal).
        """
        import pandas as pd

        symbol = symbol.upper()
        path = self._universe_cache_path(symbol, expiry, as_of)
        if path.exists():
            try:
                df = pd.read_parquet(path)
                return df.to_dict("records")
            except Exception as exc:
                logger.warning("[options_cache] unreadable universe %s: %s", path, exc)

        contracts = self.client.list_contracts(
            symbol, as_of=as_of, strike_min=strike_min, strike_max=strike_max
        )
        wanted = [
            c for c in contracts
            if c.get("expiration_date") == expiry.isoformat()
            and c.get("strike_price") is not None
        ]
        rows = [
            {
                "ticker": c["ticker"],
                "strike": float(c["strike_price"]),
                "contract_type": c.get("contract_type"),
                "expiration_date": c.get("expiration_date"),
            }
            for c in wanted
        ]
        if rows:
            pd.DataFrame(rows).to_parquet(path, index=False)
            logger.info("[options_cache] universe %s %s: %d contracts", symbol, expiry, len(rows))
        return rows

    # -- contract series -----------------------------------------------------

    def get_contract_bars(self, ticker: str, start: date, end: date) -> dict[date, dict]:
        """Full daily series for one option contract, cached. {date: {close, vwap, volume}}."""
        import pandas as pd

        path = self._contract_cache_path(ticker)
        df: Optional[pd.DataFrame] = None
        if path.exists():
            try:
                df = pd.read_parquet(path)
            except Exception as exc:
                logger.warning("[options_cache] unreadable contract %s: %s", path, exc)
        if df is None or df.empty:
            bars = self.client.daily_bars(ticker, start, end)
            rows = [
                {
                    "date": _bar_date(b["t"]),
                    "close": float(b.get("c", 0.0)),
                    "vwap": float(b.get("vw", 0.0) or 0.0),
                    "volume": int(b.get("v", 0) or 0),
                }
                for b in bars
                if b.get("c") is not None
            ]
            df = pd.DataFrame(rows)
            if df.empty:
                # Persist an empty frame so we never re-request a dead ticker.
                pd.DataFrame(columns=["date", "close", "vwap", "volume"]).to_parquet(path, index=False)
                return {}
            df.to_parquet(path, index=False)
            logger.info("[options_cache] cached %d bars for %s", len(df), ticker)
        out: dict[date, dict] = {}
        for _, row in df.iterrows():
            out[_to_date(row["date"])] = {
                "close": float(row["close"]),
                "vwap": float(row.get("vwap", 0.0) or 0.0),
                "volume": int(row.get("volume", 0) or 0),
            }
        return out

    # -- chain construction --------------------------------------------------

    def get_chain(
        self,
        symbol: str,
        as_of: datetime,
        target_dte: int,
        strike_band: Optional[tuple[float, float]] = None,
        strike_step: float = 1.0,
    ) -> Optional[OptionsChain]:
        """Build a real historical chain for (symbol, as_of) — ChainProvider protocol.

        * expiry: nearest monthly (third Friday) with DTE >= target_dte
        * strikes: a % ladder around the spot price on ``as_of``; pass
          ``strike_band=(lo, hi)`` to override with a focused absolute band
          and ``strike_step`` (e.g. 5.0) to skip intermediate $1 strikes —
          both reduce API calls when only a narrow strike window is tradable
        * contract prices: daily close/VWAP on ``as_of`` (modeled bid/ask around it)
        * IV: Black-Scholes inversion from close; Greeks via engine's calculator
        """
        symbol = symbol.upper()
        as_of_date = as_of.date()
        expiry = next_monthly_expiry(as_of_date, target_dte)
        if expiry is None:
            logger.warning("[options_cache] no monthly expiry >= %d DTE for %s", target_dte, symbol)
            return None

        # Underlying spot as of the signal date (fall back to most recent prior bar).
        bars = self.get_underlying_bars(
            symbol, as_of_date - timedelta(days=20), expiry + timedelta(days=1)
        )
        prior_dates = sorted(d for d in bars if d <= as_of_date)
        if not prior_dates:
            logger.warning("[options_cache] no underlying bars <= %s for %s", as_of_date, symbol)
            return None
        spot_date = prior_dates[-1]
        spot_row = bars[spot_date]
        spot = spot_row["close"]
        if spot <= 0:
            return None

        # Universe verification (one reference call per (symbol, expiry, as_of)
        # on first use). Fetch a WIDE band — the theoretical 30-delta strike can
        # sit far OTM during vol spikes (e.g. 2025-03-13 crash: ~15% OTM), so a
        # narrow universe would silently drop the signal's rungs.
        universe = self.get_universe(
            symbol, expiry, spot_date, spot * 0.85, spot * 1.18
        )
        universe_map = {(u["strike"], u["contract_type"]): u["ticker"] for u in universe}

        # Ladder = REAL listed strikes (from the reference universe) inside the
        # focused band, spaced >= strike_step. Building the ladder from the
        # universe instead of a synthetic integer grid is load-bearing: Polygon's
        # reference data carries phantom off-grid strikes (e.g. QQQ x.78
        # artifacts alongside the real x.00/x.50 grid) and per-symbol spacing
        # differences, so a synthetic grid silently matches nothing.
        def _clean_strike(s: float) -> bool:
            cents = int(round(s * 1000)) % 1000
            return cents in (0, 500)  # integer or half-dollar strikes only

        real_strikes = sorted(
            {float(u["strike"]) for u in universe if _clean_strike(float(u["strike"]))}
        )
        if strike_band is not None:
            lo, hi = strike_band
        else:
            lo = spot * (1 - self.ladder_band_pct)
            hi = spot * (1 + self.ladder_band_pct)
        strikes: list[float] = []
        last: Optional[float] = None
        min_gap = max(strike_step, 0.5) - 1e-9
        for s in real_strikes:
            if s < lo or s > hi:
                continue
            if last is None or s - last >= min_gap:
                strikes.append(s)
                last = s

        calls: list[OptionsContract] = []
        puts: list[OptionsContract] = []
        for strike in strikes:
            for opt_type in ("call", "put"):
                ticker = option_ticker(symbol, expiry, opt_type, strike)
                if universe_map and (strike, opt_type) not in universe_map:
                    continue  # strike never listed for this expiry
                series = self.get_contract_bars(
                    ticker,
                    max(expiry - timedelta(days=90), as_of_date - timedelta(days=10)),
                    expiry,
                )
                if spot_date not in series:
                    continue
                row = series[spot_date]
                mid = row["vwap"] if row["vwap"] > 0 else row["close"]
                if mid <= 0:
                    continue
                iv = implied_volatility(
                    mid, spot, strike, expiry, spot_date, opt_type, self.risk_free_rate
                )
                half = self.relative_half_spread
                contract = OptionsContract(
                    strike=strike,
                    expiry=expiry,
                    option_type=opt_type,
                    bid=round(mid * (1 - half), 4),
                    ask=round(mid * (1 + half), 4),
                    mid=round(mid, 4),
                    delta=0.0,
                    gamma=0.0,
                    theta=0.0,
                    vega=0.0,
                    iv=iv,
                    volume=row["volume"],
                    oi=0,
                    in_the_money=(spot > strike) if opt_type == "call" else (strike > spot),
                    last_price=round(row["close"], 4),
                )
                if iv > 0 and spot > 0:
                    from options.greeks_monitor import calculate_greeks

                    T = max((expiry - spot_date).days, 1) / 365.0
                    try:
                        g = calculate_greeks(
                            S=spot, K=strike, T=T, r=self.risk_free_rate,
                            sigma=iv, option_type=opt_type,
                        )
                        contract.delta = g["delta"]
                        contract.gamma = g["gamma"]
                        contract.theta = g["theta"]
                        contract.vega = g["vega"]
                    except Exception as exc:
                        logger.debug("[options_cache] greeks failed %s: %s", ticker, exc)
                (calls if opt_type == "call" else puts).append(contract)

        if not calls and not puts:
            logger.warning(
                "[options_cache] empty chain %s %s as_of=%s (spot=%.2f)",
                symbol, expiry, as_of_date, spot,
            )
            return None

        chain = OptionsChain(
            symbol=symbol,
            expiry=expiry,
            underlying_price=round(spot, 4),
            iv_rank=50.0,  # IV rank needs a term-structure db — out of scope for replay
            calls=calls,
            puts=puts,
            fetched_at=datetime.utcnow(),
        )
        logger.info(
            "[options_cache] chain %s %s as_of=%s spot=%.2f calls=%d puts=%d",
            symbol, expiry, as_of_date, spot, len(calls), len(puts),
        )
        return chain

    # -- provenance ----------------------------------------------------------

    def write_manifest(self, **extra: object) -> None:
        manifest = {
            "generated_at": datetime.utcnow().isoformat(),
            "source": "Polygon.io (engine POLYGON_API_KEY)",
            "tier_notes": (
                "reference + daily aggregates OK; options snapshot (bid/ask/greeks) "
                "403 NOT_AUTHORIZED on this tier -> bid/ask modeled via relative_half_spread"
            ),
            "relative_half_spread": self.relative_half_spread,
            "ladder_step_pct": self.ladder_step_pct,
            "ladder_band_pct": self.ladder_band_pct,
            "risk_free_rate": self.risk_free_rate,
            **extra,
        }
        (self.cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
