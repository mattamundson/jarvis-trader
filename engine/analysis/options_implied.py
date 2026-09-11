"""
JARVIS TRADER — SPY/QQQ market-implied options analytics
=========================================================
Pure computation for the /signals dashboard Options section: ATM-straddle
expected move, delta-implied probability ladder, IV context, and the VIX/VIX3M
term-structure regime — all from the free CBOE delayed feeds. Consumed by
``engine/scripts/options_signals_snapshot.py`` (generator) and served by
``engine/routers/options_signals_router.py``.

(Named ``options_implied`` rather than ``options_signals`` because
``analysis/options_signals.py`` already exists — the legacy Phase 5.2 vertical
spread generator — and because "implied" is the honest description of what
this module computes.)

HONESTY CONTRACT (binding, from the June-2026 options-vrp research): none of
this claims a predictive edge. Every number is *market-implied* — what the
options market currently prices in, from 15-minute-delayed quotes. The
probability ladder uses vendor CALL deltas, i.e. approximately N(d1), which
slightly OVERSTATES the true risk-neutral P(close above) = N(d2) for
short-dated options; we label everything "delta-implied" (the industry
convention) and disclose it in the snapshot's ``disclaimer`` field. The one
validated transferable asset from that research is the VIX/VIX3M term-structure
regime classifier ported verbatim below (``classify_term_structure``).

No LLM, no DB, no broker, no execution wiring. Pure stdlib + httpx.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CBOE_CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_VIX3M_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv"

# OCC/OSI option symbol, e.g. "SPY260717C00628000" (from the archived
# options-vrp ingest.py — root, YYMMDD, C/P, strike*1000).
OCC_RE = re.compile(r"^([A-Z]+?)(\d{6})([CP])(\d{8})$")

# Term-structure dead-band: |VIX3M - VIX| within 0.5 vol points is FLAT.
# Verbatim from Archive/2026/options-vrp/options_vrp/vrp_signal.py.
FLAT_BAND = 0.005

DEFAULT_SYMBOLS = ("SPY", "QQQ")
LADDER_MULTIPLES = (1.0, 0.5, 0.0, -0.5, -1.0)

DATA_DELAYED_MINUTES = 15
# 30-min generation cadence + 15-min grace before the dashboard flags STALE.
STALE_AFTER_S = 2700
# Inside RTH, a chain quote timestamp older than this suggests a market
# holiday (CBOE keeps serving the last session's snapshot).
QUOTE_STALE_S = 3600

DISCLAIMER = (
    "Market-implied analytics from 15-minute-delayed CBOE quotes. These figures "
    "are what the options market currently prices in — no validated predictive "
    "edge, not trade signals. Probabilities are delta-implied (risk-neutral) "
    "approximations."
)

_CT = ZoneInfo("America/Chicago")

FetchJson = Callable[[str], Awaitable[dict]]
FetchText = Callable[[str], Awaitable[str]]


class OptionsImpliedError(Exception):
    """A chain is unusable (no spot, no contracts, no future expiries)."""


# ---------------------------------------------------------------------------
# Chain parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contract:
    root: str
    expiry: date
    right: str  # "C" | "P"
    strike: float
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    last_trade: Optional[float]
    iv: Optional[float]
    delta: Optional[float]
    open_interest: int
    volume: int


def parse_occ(occ: str) -> Optional[tuple[str, date, str, float]]:
    """Parse an OCC/OSI symbol → (root, expiry, right, strike). None on no-match."""
    m = OCC_RE.match(occ or "")
    if not m:
        return None
    root, yymmdd, right, strike8 = m.groups()
    try:
        expiry = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
    except ValueError:
        return None
    return root, expiry, right, int(strike8) / 1000.0


def _pos_or_none(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _parse_quote_ts(ts_str: str) -> Optional[int]:
    """CBOE top-level timestamp ("YYYY-MM-DD HH:MM:SS") → epoch seconds.

    The wall time is UTC, not US/Eastern — verified live 2026-07-16: a fetch at
    18:56 UTC carried "…18:55:31", which back-solves to the observed epoch only
    when read as UTC (an ET read would place the quote 4h in the future)."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts_str[:19], fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def parse_chain(raw: dict, symbol: str) -> tuple[float, Optional[int], list[Contract]]:
    """CBOE delayed-chain JSON → (spot, quote_ts_epoch, contracts).

    Filters to contracts whose OCC root == ``symbol`` exactly (SPY/QQQ weeklies
    trade under the plain root; the filter defensively drops anything else).
    """
    data = raw.get("data") or {}
    spot = data.get("current_price")
    if not isinstance(spot, (int, float)) or spot <= 0:
        raise OptionsImpliedError(f"{symbol}: chain has no usable current_price")

    quote_ts = _parse_quote_ts(raw.get("timestamp") or data.get("timestamp") or "")

    contracts: list[Contract] = []
    for opt in data.get("options") or []:
        parsed = parse_occ(opt.get("option", ""))
        if parsed is None:
            continue
        root, expiry, right, strike = parsed
        if root != symbol:
            continue
        bid = _pos_or_none(opt.get("bid"))
        ask = _pos_or_none(opt.get("ask"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        delta = opt.get("delta")
        contracts.append(
            Contract(
                root=root,
                expiry=expiry,
                right=right,
                strike=strike,
                bid=bid,
                ask=ask,
                mid=mid,
                last_trade=_pos_or_none(opt.get("last_trade_price")),
                iv=_pos_or_none(opt.get("iv")),
                delta=float(delta) if isinstance(delta, (int, float)) else None,
                open_interest=int(opt.get("open_interest") or 0),
                volume=int(opt.get("volume") or 0),
            )
        )
    if not contracts:
        raise OptionsImpliedError(f"{symbol}: chain parsed to zero contracts")
    return float(spot), quote_ts, contracts


# ---------------------------------------------------------------------------
# Expiry / ATM selection
# ---------------------------------------------------------------------------


def select_expiries(expiries: set[date], today_ct: date) -> tuple[date, Optional[date]]:
    """→ (nearest, end_of_week | None).

    nearest = first expiry >= today. end_of_week = latest expiry within this
    calendar week (<= Friday). When they coincide (it's Friday, or a
    holiday-shortened week), the second horizon is promoted to next week's
    latest-Friday-or-earlier expiry; None when no such expiry is listed.
    """
    future = [e for e in expiries if e >= today_ct]
    if not future:
        raise OptionsImpliedError("no expiries on or after today")
    nearest = min(future)

    friday = today_ct + timedelta(days=4 - today_ct.weekday())
    this_week = [e for e in future if e <= friday]
    eow = max(this_week) if this_week else None

    if eow is None or eow == nearest:
        next_friday = friday + timedelta(days=7)
        next_week = [e for e in future if nearest < e <= next_friday]
        eow = max(next_week) if next_week else None
    return nearest, eow


def atm_strike(contracts: list[Contract], expiry: date, spot: float) -> Optional[float]:
    """Strike closest to spot that has BOTH a call and a put with a live mid.

    Ties break to the lower strike (deterministic). None when no strike
    qualifies (dead chain for that expiry).
    """
    calls = {c.strike for c in contracts if c.expiry == expiry and c.right == "C" and c.mid is not None}
    puts = {c.strike for c in contracts if c.expiry == expiry and c.right == "P" and c.mid is not None}
    candidates = calls & puts
    if not candidates:
        return None
    return min(candidates, key=lambda k: (abs(k - spot), k))


# ---------------------------------------------------------------------------
# Expected move + probability ladder
# ---------------------------------------------------------------------------


def _leg(contracts: list[Contract], expiry: date, right: str, strike: float) -> Optional[Contract]:
    for c in contracts:
        if c.expiry == expiry and c.right == right and c.strike == strike:
            return c
    return None


def straddle_expected_move(contracts: list[Contract], expiry: date, spot: float) -> dict:
    """ATM-straddle expected move: call mid + put mid at the ATM strike.

    A leg with no mid falls back to last_trade_price (> 0) with quality
    "degraded" (last trade may be stale); no price at all → expected_move None.
    """
    notes: list[str] = []
    strike = atm_strike(contracts, expiry, spot)
    quality = "ok"

    if strike is None:
        # No strike with live mids on both sides — retry ATM selection on any
        # strike present both sides, pricing legs off last_trade.
        both = {c.strike for c in contracts if c.expiry == expiry and c.right == "C"} & {
            c.strike for c in contracts if c.expiry == expiry and c.right == "P"
        }
        if not both:
            raise OptionsImpliedError(f"no call/put strike pairs for expiry {expiry}")
        strike = min(both, key=lambda k: (abs(k - spot), k))
        quality = "degraded"
        notes.append("no strike with live two-sided quotes; ATM chosen without mids")

    leg_prices: list[float] = []
    ivs: list[float] = []
    for right in ("C", "P"):
        leg = _leg(contracts, expiry, right, strike)
        price = leg.mid if leg else None
        if price is None and leg is not None and leg.last_trade is not None:
            price = leg.last_trade
            quality = "degraded"
            notes.append(f"ATM {right} mid missing; used last_trade_price")
        if price is not None:
            leg_prices.append(price)
        if leg is not None and leg.iv is not None:
            ivs.append(leg.iv)

    straddle_mid = sum(leg_prices) if len(leg_prices) == 2 else None
    if straddle_mid is None:
        quality = "degraded"
        notes.append("ATM straddle unpriceable — expected move unavailable")

    return {
        "atm_strike": strike,
        "atm_iv": (sum(ivs) / len(ivs)) if ivs else None,
        "straddle_mid": straddle_mid,
        "expected_move_abs": straddle_mid,
        "expected_move_pct": (straddle_mid / spot) if straddle_mid else None,
        "quality": quality,
        "notes": notes,
    }


def prob_ladder(
    contracts: list[Contract], expiry: date, spot: float, em_abs: Optional[float]
) -> list[dict]:
    """Delta-implied P(close above level) at spot ± {0, ±0.5, ±1.0} × expected move.

    Uses vendor CALL deltas only (put deltas are negative — never mix signs),
    linearly interpolated on strike between the bracketing listed strikes. A
    level exactly on a listed strike uses that strike's delta unchanged; a
    level outside the listed range gets p_above None (rendered "—"; we never
    extrapolate). Empty when the expected move itself is unavailable.

    Touch/failure columns (2026-09-04, Amo's spec): each row also carries
    ``p_touch`` and ``p_fail``. Per the reflection approximation (barrier
    pricing's first-passage rule under zero-drift GBM), P(touch) = 2 × the
    probability of closing BEYOND the level: 2 × p_above for an upper barrier
    (level ≥ spot), 2 × (1 − p_above) for a lower barrier; clamped at 1.0.
    Like the ladder itself these are MARKET-IMPLIED estimates under the
    delta/N(d1) convention, not calibrated first-passage probabilities — the
    constant 2.0 ignores the (typically negative) risk-neutral drift and the
    vol smile. They are labeled "reflection-implied" everywhere they render.
    """
    if em_abs is None:
        return []
    calls = sorted(
        (
            c
            for c in contracts
            if c.expiry == expiry and c.right == "C" and c.delta is not None and 0.0 < c.delta < 1.0
        ),
        key=lambda c: c.strike,
    )
    strikes = [c.strike for c in calls]
    deltas = [c.delta for c in calls]

    def _interp(level: float) -> Optional[float]:
        """Linearly interpolated CALL delta at ``level``; None outside the range."""
        if len(strikes) >= 2 and strikes[0] <= level <= strikes[-1]:
            i = bisect_left(strikes, level)
            if i < len(strikes) and strikes[i] == level:
                return deltas[i]
            k_lo, k_hi = strikes[i - 1], strikes[i]
            d_lo, d_hi = deltas[i - 1], deltas[i]
            return d_lo + (d_hi - d_lo) * (level - k_lo) / (k_hi - k_lo)
        return None

    ladder: list[dict] = []
    for mult in LADDER_MULTIPLES:
        level = spot + mult * em_abs
        p_above = _interp(level)
        p_touch: Optional[float] = None
        if p_above is not None:
            # Reflection approximation (zero-drift GBM first passage). Upper
            # barrier (level >= spot): P(touch) = 2 × P(close >= level)
            # = 2 × p_above. Lower barrier (level < spot): P(touch)
            # = 2 × P(close <= level) = 2 × (1 − p_above). The spot row reads
            # ≈ 2 × 0.5 = 1.0 either way (spot is touched by construction),
            # and deeper-OTM rows monotonically decay toward 0.
            p_close_beyond = p_above if level >= spot else (1.0 - p_above)
            p_touch = min(1.0, 2.0 * p_close_beyond)
        p_fail = (1.0 - p_touch) if p_touch is not None else None
        label = "spot" if mult == 0.0 else f"{mult:+.1f} EM"
        ladder.append(
            {
                "multiple": mult,
                "label": label,
                "level": round(level, 2),
                "p_above": round(p_above, 4) if p_above is not None else None,
                "p_touch": round(p_touch, 4) if p_touch is not None else None,
                "p_fail": round(p_fail, 4) if p_fail is not None else None,
            }
        )
    return ladder


def build_horizon(
    contracts: list[Contract],
    expiry: date,
    spot: float,
    label: str,
    today_ct: date,
) -> dict:
    em = straddle_expected_move(contracts, expiry, spot)
    dte = (expiry - today_ct).days
    notes = list(em["notes"])
    if dte == 0:
        notes.append("0DTE — expires at today's close; deltas saturate late in the session")
    return {
        "label": label,
        "expiry": expiry.isoformat(),
        "dte_calendar": dte,
        "atm_strike": em["atm_strike"],
        "atm_iv": round(em["atm_iv"], 4) if em["atm_iv"] is not None else None,
        "straddle_mid": round(em["straddle_mid"], 4) if em["straddle_mid"] is not None else None,
        "expected_move_abs": round(em["expected_move_abs"], 4)
        if em["expected_move_abs"] is not None
        else None,
        "expected_move_pct": round(em["expected_move_pct"], 6)
        if em["expected_move_pct"] is not None
        else None,
        "prob_ladder": prob_ladder(contracts, expiry, spot, em["expected_move_abs"]),
        "quality": em["quality"],
        "notes": notes,
    }


def build_symbol_block(symbol: str, raw: dict, now_ct: datetime) -> dict:
    """One symbol's chain → snapshot block. Raises OptionsImpliedError when unusable."""
    spot, quote_ts, contracts = parse_chain(raw, symbol)
    today_ct = now_ct.date()
    nearest, eow = select_expiries({c.expiry for c in contracts}, today_ct)

    horizons = [build_horizon(contracts, nearest, spot, "nearest", today_ct)]
    if eow is not None:
        horizons.append(build_horizon(contracts, eow, spot, "end_of_week", today_ct))

    # Holiday guard without a holiday calendar: inside RTH a fresh fetch should
    # never be an hour old — CBOE serving the prior session's snapshot means a
    # market holiday (or a feed outage); either way, degrade honestly.
    if quote_ts is not None and now_ct.timestamp() - quote_ts > QUOTE_STALE_S:
        for h in horizons:
            h["quality"] = "degraded"
            h["notes"].append("quote timestamp >60 min old — market holiday or feed outage?")

    return {"spot": round(spot, 4), "quote_ts": quote_ts, "horizons": horizons}


# ---------------------------------------------------------------------------
# VIX / VIX3M term-structure regime
# ---------------------------------------------------------------------------


def classify_term_structure(
    vix: float, vix3m: float, flat_band: float = FLAT_BAND
) -> tuple[str, float]:
    """Verbatim port of options_vrp.vrp_signal.classify_term_structure (the one
    validated transferable asset from the June-2026 research). Inputs are index
    LEVELS (e.g. 16.4); slope is decimal vol (vix3m/100 − vix/100)."""
    slope = float(vix3m) / 100.0 - float(vix) / 100.0
    if slope > flat_band:
        return "CONTANGO", slope
    if slope < -flat_band:
        return "BACKWARDATION", slope
    return "FLAT", slope


def parse_vix_csv(text: str) -> list[tuple[date, float]]:
    """CBOE daily index CSV (DATE,OPEN,HIGH,LOW,CLOSE) → [(date, close)].

    Handles both ISO and MM/DD/YYYY date styles; skips unparseable rows."""
    rows: list[tuple[date, float]] = []
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 5:
            continue
        raw_date = rec[0].strip()
        d: Optional[date] = None
        try:
            d = date.fromisoformat(raw_date)
        except ValueError:
            try:
                d = datetime.strptime(raw_date, "%m/%d/%Y").date()
            except ValueError:
                continue  # header or junk row
        try:
            close = float(rec[4])
        except ValueError:
            continue
        rows.append((d, close))
    rows.sort(key=lambda r: r[0])
    return rows


def build_regime_block(
    vix_rows: list[tuple[date, float]], vix3m_rows: list[tuple[date, float]]
) -> dict:
    """Latest common VIX/VIX3M date → regime block with a 1-year VIX percentile."""
    if not vix_rows or not vix3m_rows:
        raise OptionsImpliedError("empty VIX/VIX3M history")
    vix_by_date = dict(vix_rows)
    vix3m_by_date = dict(vix3m_rows)
    common = sorted(set(vix_by_date) & set(vix3m_by_date))
    if not common:
        raise OptionsImpliedError("no common VIX/VIX3M dates")
    as_of = common[-1]
    vix, vix3m = vix_by_date[as_of], vix3m_by_date[as_of]
    regime, slope = classify_term_structure(vix, vix3m)

    window = [close for d, close in vix_rows if d <= as_of][-252:]
    percentile = sum(1 for c in window if c <= vix) / len(window)

    return {
        "vix": round(vix, 2),
        "vix3m": round(vix3m, 2),
        "slope": round(slope, 4),
        "regime": regime,
        "vix_percentile_1y": round(percentile, 4),
        "as_of_date": as_of.isoformat(),
        "source": "CBOE daily index CSVs (prior close; refreshed once per day)",
    }


# ---------------------------------------------------------------------------
# Fetchers + snapshot orchestration
# ---------------------------------------------------------------------------

# QQQ's chain is ~12k contracts / several MB — the house 10 s timeout is too
# tight for this endpoint; 30 s gives comfortable headroom.
_HTTP_TIMEOUT_S = 30.0
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}


async def _default_fetch_json(url: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S, headers=_HTTP_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _default_fetch_text(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S, headers=_HTTP_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def fetch_regime_block(fetch_text: Optional[FetchText] = None) -> dict:
    """Fetch both CBOE daily CSVs and build the regime block."""
    fetch = fetch_text or _default_fetch_text
    vix_rows = parse_vix_csv(await fetch(CBOE_VIX_URL))
    vix3m_rows = parse_vix_csv(await fetch(CBOE_VIX3M_URL))
    return build_regime_block(vix_rows, vix3m_rows)


async def build_snapshot(
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    *,
    fetch_json: Optional[FetchJson] = None,
    regime: Optional[dict] = None,
    regime_error: Optional[str] = None,
    now_ct: Optional[datetime] = None,
) -> tuple[dict, int]:
    """Fetch every symbol's chain and assemble the snapshot dict.

    Per-symbol failures degrade to ``symbols[sym] = None`` + an errors entry
    (data_quality "partial", exit code 2) — one bad chain never sinks the run.
    ``regime`` is prebuilt by the caller (the generator owns its daily cache);
    ``regime_error`` carries the caller's fetch-failure message into errors[].
    Returns (snapshot, exit_code) with exit_code 0 (all ok) or 2 (partial).
    """
    fetch = fetch_json or _default_fetch_json
    now = now_ct or datetime.now(_CT)

    blocks: dict[str, Optional[dict]] = {}
    errors: list[str] = []
    for symbol in symbols:
        try:
            raw = await fetch(CBOE_CHAIN_URL.format(symbol=symbol))
            blocks[symbol] = build_symbol_block(symbol, raw, now)
        except Exception as exc:  # noqa: BLE001 — degrade per-symbol, never sink the run
            logger.warning("%s chain failed: %s", symbol, exc)
            blocks[symbol] = None
            errors.append(f"{symbol}: {exc}")

    if regime is None:
        errors.append(regime_error or "regime: VIX/VIX3M unavailable")

    quote_timestamps = [b["quote_ts"] for b in blocks.values() if b and b["quote_ts"]]
    partial = regime is None or any(b is None for b in blocks.values())

    snapshot = {
        "schema_version": 1,
        "generated_at": int(now.timestamp()),
        "quote_ts": min(quote_timestamps) if quote_timestamps else None,
        "data_delayed_minutes": DATA_DELAYED_MINUTES,
        "stale_after_s": STALE_AFTER_S,
        "data_quality": "partial" if partial else "ok",
        "errors": errors,
        "disclaimer": DISCLAIMER,
        "regime": regime,
        "symbols": blocks,
    }
    return snapshot, 2 if partial else 0
