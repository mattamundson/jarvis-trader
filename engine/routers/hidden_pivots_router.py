"""
HiddenPivots Pattern Scanner — API Router
Endpoints for scanning symbols for HP patterns, analyzing individual symbols,
and fetching the HP level ladder.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hidden-pivots", tags=["hidden-pivots"])

# Dependency injection
_data_manager = None
_config = None


def inject_dependencies(data_manager, config) -> None:
    global _data_manager, _config
    _data_manager = data_manager
    _config = config


# ── Request / Response schemas ─────────────────────────────────────────────────


class ScreenRequest(BaseModel):
    symbols: list[str]
    timeframe: str = "1d"
    benchmark: str = "SPY"


class HPSignal(BaseModel):
    symbol: str
    timeframe: str
    pattern: Optional[str]
    bias: str
    trigger_price: Optional[float]
    tight_stop: Optional[float]
    riskier_stop: Optional[float]
    targets: list[float]
    hp_ou_level: Optional[float]
    ema_alignment: str
    rs_rw_score: float
    rs_rw_label: str
    soh: bool
    oscillator_state: str
    bars_since_cross: int = -1
    last_cross_dir: str = "none"
    confidence: float
    notes: str


class ScanResponse(BaseModel):
    scan_time: str
    symbols_scanned: int
    signals: list[HPSignal]
    soh_symbols: list[str]
    watch_symbols: list[str]
    # Full per-symbol result for every scanned name (incl. WATCH/SOH), so UIs can
    # render the level ladder for non-armed setups. Additive; `signals` /
    # `soh_symbols` / `watch_symbols` keep their original meaning.
    details: list[HPSignal] = Field(default_factory=list)
    # Cache/single-flight metadata. Existing dashboard consumers can ignore
    # these additive fields; they let refresh callers know when the response is
    # a stale-but-safe cache served while another scan is already running.
    refresh_in_progress: bool = False
    cache_status: str = "fresh"


# ── Helpers ────────────────────────────────────────────────────────────────────

# Fallback scan universe when settings.SCAN_SYMBOLS is unavailable (e.g. tests).
# Kept in sync with config.Settings.SCAN_SYMBOLS. Analysis-only — the HP scanner
# never routes orders, so this is intentionally broader than the trade watchlist.
DEFAULT_WATCHLIST = [
    # futures
    "MES",
    "MNQ",
    "MGC",
    "MCL",
    # ETFs / sector
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "GLD",
    "SLV",
    "SMH",
    "XLE",
    # mega-cap / liquid single names
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AMD",
    "AVGO",
    "NFLX",
    # high-options-volume momentum names
    "PLTR",
    "COIN",
    "MSTR",
    "MU",
    "CRM",
    "UBER",
    "JPM",
    "BAC",
    "XOM",
    "LLY",
    "COST",
]

_last_scan_cache: Optional[ScanResponse] = None
_scan_in_progress = False
_scan_lock: Optional[asyncio.Lock] = None
_MAX_SCAN_CONCURRENCY = 6
_PER_SYMBOL_SCAN_TIMEOUT_SECONDS = 20.0


def _get_watchlist() -> list[str]:
    if _config is not None:
        symbols = getattr(_config, "SCAN_SYMBOLS", None)
        if symbols:
            return list(symbols)
    return DEFAULT_WATCHLIST


def _get_scan_lock() -> asyncio.Lock:
    global _scan_lock
    if _scan_lock is None:
        _scan_lock = asyncio.Lock()
    return _scan_lock


def _copy_scan_response(
    response: ScanResponse,
    *,
    refresh_in_progress: bool,
    cache_status: str,
) -> ScanResponse:
    return response.model_copy(
        update={
            "refresh_in_progress": refresh_in_progress,
            "cache_status": cache_status,
        }
    )


async def _run_bounded_scans(
    symbols: list[str],
    timeframe: str,
    benchmark_df=None,
) -> list[Optional[HPSignal]]:
    """Run per-symbol scans without stampeding the engine event loop."""
    semaphore = asyncio.Semaphore(_MAX_SCAN_CONCURRENCY)

    async def run_one(symbol: str) -> Optional[HPSignal]:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    _fetch_and_scan(symbol, timeframe, benchmark_df),
                    timeout=_PER_SYMBOL_SCAN_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "HP scan timed out for %s/%s after %.1fs",
                    symbol,
                    timeframe,
                    _PER_SYMBOL_SCAN_TIMEOUT_SECONDS,
                )
                return None

    return await asyncio.gather(*(run_one(sym) for sym in symbols), return_exceptions=False)


# ── Price-coverage floor (PRB-21) ───────────────────────────────────────────────
# The HP scan (above) covers the full watchlist via get_bars(), which has its own
# multi-tier waterfall. The dashboard's separate LIVE-PRICE ticker column goes
# through /prices/snapshot -> MarketDataManager.get_current_price(), whose last
# resort is a CSV backtest-cache read (Tier 5). When IBKR is down and Polygon's
# 4-calls/60s free-tier rate limit is exhausted (engine/data/market_data.py
# PolygonDataConnector._RATE_LIMIT), a symbol with no CSV cache has zero floor
# and shows "--" with certainty. Only 11 of the 33 watchlist symbols have ever
# been backtested and so only those 11 have a cache file. Rather than let the
# other 22 poll a floor that structurally can't exist, the dashboard should only
# poll live prices for the covered subset -- pattern/level scanning is
# unaffected (still runs the full watchlist above). See PRB-21 for the b3
# (Polygon batch snapshot) option ruled out: live probe against the configured
# key returned 403 NOT_AUTHORIZED (plan doesn't include the multi-ticker
# snapshot endpoint), and b2 (proactively seeding cache for all 33) is tracked
# as PRB-22, a separate follow-up.
_CSV_CACHE_DIR = Path(__file__).resolve().parent.parent / "backtest" / "cache"


def _has_csv_price_floor(symbol: str) -> bool:
    """True if a 1d CSV backtest-cache file exists for ``symbol``.

    Mirrors the glob pattern MarketDataManager._load_csv_cache uses for its
    Tier-5 (CSV cache) fallback inside get_current_price — kept in sync
    deliberately rather than imported, since this only needs a cheap existence
    check, not a bar load.
    """
    try:
        return next(_CSV_CACHE_DIR.glob(f"{symbol.upper()}_*_1d.csv"), None) is not None
    except OSError:
        return False


def get_price_covered_watchlist() -> list[str]:
    """Subset of the current watchlist that has a real price-fallback floor."""
    return [s for s in _get_watchlist() if _has_csv_price_floor(s)]


async def _fetch_and_scan(
    symbol: str,
    timeframe: str,
    benchmark_df=None,
) -> Optional[HPSignal]:
    """Fetch bars for one symbol and run the HP scan."""
    try:
        from analysis.hidden_pivots import full_hidden_pivots_scan

        # Map timeframe strings to lookback days
        lookback_map = {"1d": 200, "1h": 30, "5m": 5, "15m": 7, "4h": 60}
        lookback = lookback_map.get(timeframe, 200)

        df = await _data_manager.get_bars(symbol, lookback_days=lookback, timeframe=timeframe)
        if df is None or df.empty:
            logger.debug("No data for %s/%s", symbol, timeframe)
            return None

        result = full_hidden_pivots_scan(symbol, df, benchmark_df=benchmark_df, timeframe=timeframe)
        return HPSignal(**result.__dict__)

    except Exception as e:
        logger.warning("HP scan failed for %s: %s", symbol, e)
        return None


async def _fetch_benchmark(benchmark: str, timeframe: str):
    """Fetch benchmark bars for r/s calculation."""
    try:
        lookback_map = {"1d": 30, "1h": 10, "5m": 2, "15m": 3, "4h": 20}
        lookback = lookback_map.get(timeframe, 30)
        return await _data_manager.get_bars(benchmark, lookback_days=lookback, timeframe=timeframe)
    except Exception as e:
        logger.debug("Benchmark fetch failed (%s): %s", benchmark, e)
        return None


async def _notify_hp_signal(sig: HPSignal) -> None:
    """Send WhatsApp alert for a high-confidence HP signal (confidence >= 0.70)."""
    try:
        from notifications.whatsapp import send_whatsapp_message

        targets_str = "-".join(f"{t:.2f}" for t in sig.targets[:3]) if sig.targets else "N/A"
        hp_ou_str = f"{sig.hp_ou_level:.2f}" if sig.hp_ou_level else "N/A"
        msg = (
            f"🎯 HP SIGNAL [{sig.timeframe.upper()}]\n"
            f"Symbol: {sig.symbol} | {sig.bias}\n"
            f"Pattern: {(sig.pattern or 'unknown').replace('_', ' ').title()}\n"
            f"Trigger: {sig.trigger_price:.2f}\n"
            f"Targets: {targets_str}\n"
            f"Tight stop: {sig.tight_stop:.2f} | Riskier: {sig.riskier_stop:.2f}\n"
            f"HP o/u: {hp_ou_str} | EMA: {sig.ema_alignment}\n"
            f"Oscillator: {sig.oscillator_state} | r/s: {sig.rs_rw_label}\n"
            f"Confidence: {sig.confidence:.0%}"
        )
        await send_whatsapp_message(msg, alert_type="hp_signal", symbol=sig.symbol)
        logger.info("HP WhatsApp alert sent for %s (%s)", sig.symbol, sig.bias)
    except Exception as e:
        logger.warning("HP WhatsApp notification failed for %s: %s", sig.symbol, e)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/scan", response_model=ScanResponse)
async def scan_watchlist(
    timeframe: str = Query("1d", description="Bar timeframe: 1d, 1h, 4h, 15m, 5m"),
    benchmark: str = Query("SPY", description="Benchmark symbol for r/s calculation"),
):
    """
    Scan all watchlist symbols for HiddenPivots patterns.
    Returns signals, SOH symbols, and WATCH setups.
    """
    global _last_scan_cache, _scan_in_progress

    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Data manager not initialized")

    # Single-flight guard: dashboard refreshes must not stack multiple full
    # watchlist scans while the engine is already saturated. If a cached report
    # exists, return it immediately and let the active refresh finish.
    if _scan_in_progress and _last_scan_cache is not None:
        return _copy_scan_response(
            _last_scan_cache,
            refresh_in_progress=True,
            cache_status="stale_while_refreshing",
        )

    scan_lock = _get_scan_lock()
    waited_for_scan = scan_lock.locked()
    if waited_for_scan and _last_scan_cache is not None:
        return _copy_scan_response(
            _last_scan_cache,
            refresh_in_progress=True,
            cache_status="stale_while_refreshing",
        )

    async with scan_lock:
        # If this request arrived while the first scan was running and there was
        # no cache yet, wait once and return the completed first scan instead of
        # immediately starting a duplicate refresh.
        if waited_for_scan and _last_scan_cache is not None:
            return _copy_scan_response(
                _last_scan_cache,
                refresh_in_progress=False,
                cache_status="fresh_after_wait",
            )

        _scan_in_progress = True
        try:
            symbols = _get_watchlist()
            benchmark_df = await _fetch_benchmark(benchmark, timeframe)
            results = await _run_bounded_scans(symbols, timeframe, benchmark_df)
        finally:
            _scan_in_progress = False

    signals = []
    soh_symbols = []
    watch_symbols = []

    for sig in results:
        if sig is None:
            continue
        if sig.soh or sig.bias == "SOH":
            soh_symbols.append(sig.symbol)
        elif sig.bias == "WATCH":
            watch_symbols.append(sig.symbol)
        elif sig.bias in ("LONG", "SHORT") and sig.confidence >= 0.5:
            signals.append(sig)

    # Sort signals by confidence descending
    signals.sort(key=lambda s: s.confidence, reverse=True)

    # Send WhatsApp alerts for high-confidence confirmed signals (confidence >= 0.70)
    for sig in signals:
        if sig.confidence >= 0.70:
            await _notify_hp_signal(sig)

    response = ScanResponse(
        scan_time=datetime.now(timezone.utc).isoformat(),
        symbols_scanned=len(symbols),
        signals=signals,
        soh_symbols=soh_symbols,
        watch_symbols=watch_symbols,
        details=[s for s in results if s is not None],
    )
    _last_scan_cache = response
    return response


@router.get("/price-coverage")
async def get_price_coverage() -> dict[str, Any]:
    """
    Which watchlist symbols currently have a real live-price fallback floor
    (PRB-21). The dashboard's live-price ticker poll should only request this
    `covered_symbols` subset -- pattern/level scanning via /scan still covers
    the full watchlist regardless.
    """
    watchlist = _get_watchlist()
    covered = get_price_covered_watchlist()
    covered_set = set(covered)
    return {
        "watchlist_size": len(watchlist),
        "covered_symbols": covered,
        "uncovered_symbols": [s for s in watchlist if s not in covered_set],
    }


@router.get("/analyze/{symbol}", response_model=HPSignal)
async def analyze_symbol(
    symbol: str,
    timeframe: str = Query("1d", description="Bar timeframe"),
    benchmark: str = Query("SPY", description="Benchmark for r/s"),
):
    """
    Full HP analysis for a single symbol.
    Returns complete HPScanResult including level ladder and pattern details.
    """
    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Data manager not initialized")

    benchmark_df = await _fetch_benchmark(benchmark, timeframe)
    result = await _fetch_and_scan(symbol.upper(), timeframe, benchmark_df)

    if result is None:
        raise HTTPException(status_code=404, detail=f"No data available for {symbol}")

    return result


@router.get("/levels/{symbol}")
async def get_hp_levels(
    symbol: str,
    timeframe: str = Query("1d", description="Bar timeframe"),
) -> dict[str, Any]:
    """
    Return just the HP level ladder for a symbol (A-B-C-D structure + fibonacci levels).
    Lightweight endpoint for dashboard overlays.
    """
    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Data manager not initialized")

    try:
        from analysis.hidden_pivots import compute_hp_ou_level

        lookback_map = {"1d": 200, "1h": 30, "5m": 5}
        lookback = lookback_map.get(timeframe, 200)
        df = await _data_manager.get_bars(
            symbol.upper(), lookback_days=lookback, timeframe=timeframe
        )

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        hp_ou, levels, swing = compute_hp_ou_level(df)

        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "hp_ou_level": round(hp_ou, 4) if hp_ou else None,
            "level_ladder": [round(l, 4) for l in levels],  # noqa: E741  # OHLC convention
            "swing_structure": (
                {
                    "a_price": round(swing.a_price, 4),
                    "b_price": round(swing.b_price, 4),
                    "c_price": round(swing.c_price, 4),
                    "d_price": round(swing.d_price, 4),
                }
                if swing
                else None
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("HP levels failed for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/screen", response_model=ScanResponse)
async def screen_symbols(request: ScreenRequest):
    """
    Run HP scan on a specific list of symbols.
    Useful for targeted screens (e.g., options candidates, sector scan).
    """
    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Data manager not initialized")

    symbols = [s.upper() for s in request.symbols]
    benchmark_df = await _fetch_benchmark(request.benchmark, request.timeframe)

    tasks = [_fetch_and_scan(sym, request.timeframe, benchmark_df) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    signals = []
    soh_symbols = []
    watch_symbols = []

    for sig in results:
        if sig is None:
            continue
        if sig.soh or sig.bias == "SOH":
            soh_symbols.append(sig.symbol)
        elif sig.bias == "WATCH":
            watch_symbols.append(sig.symbol)
        elif sig.bias in ("LONG", "SHORT") and sig.confidence >= 0.4:
            signals.append(sig)

    signals.sort(key=lambda s: s.confidence, reverse=True)

    return ScanResponse(
        scan_time=datetime.now(timezone.utc).isoformat(),
        symbols_scanned=len(symbols),
        signals=signals,
        soh_symbols=soh_symbols,
        watch_symbols=watch_symbols,
        details=[s for s in results if s is not None],
    )


@router.get("/report", response_model=Optional[ScanResponse])
async def get_last_report():
    """
    Return the most recent cached scan result without re-fetching data.
    Use this for dashboard polling — call /scan to refresh.
    """
    if _last_scan_cache is None:
        return None
    return _last_scan_cache


@router.get("/confluence/{symbol}")
async def check_confluence(
    symbol: str,
    timeframe: str = Query("1d", description="Bar timeframe"),
    benchmark: str = Query("SPY", description="Benchmark for r/s"),
) -> dict:
    """
    Cross-check HP pattern against last 5-stage pipeline decision for dual confirmation.

    HIGH_CONVICTION: HP signal + pipeline both agree direction (confidence >= 0.70)
    WEAK: Both agree but confidence < 0.70
    DIVERGENT: HP and pipeline disagree
    HP_ONLY: HP signal found, no pipeline decision available
    NO_SIGNAL: Neither system has a directional signal
    """
    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Data manager not initialized")

    sym = symbol.upper()

    # Run HP scan
    benchmark_df = await _fetch_benchmark(benchmark, timeframe)
    hp_result = await _fetch_and_scan(sym, timeframe, benchmark_df)

    # Fetch last pipeline decision for this symbol
    pipeline_decision = None
    pipeline_direction = "HOLD"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "http://localhost:8010/decisions/recent",
                params={"limit": 5},
            )
            if resp.status_code == 200:
                decisions = resp.json()
                # Find most recent decision for this symbol
                for d in decisions:
                    if d.get("symbol", "").upper() == sym:
                        pipeline_decision = d
                        pipeline_direction = d.get("direction", "HOLD")
                        break
    except Exception as e:
        logger.debug("Pipeline decision fetch failed for %s: %s", sym, e)

    hp_bias = hp_result.bias if hp_result else "WATCH"
    hp_conf = hp_result.confidence if hp_result else 0.0

    # Determine alignment
    both_long = hp_bias == "LONG" and pipeline_direction == "LONG"
    both_short = hp_bias == "SHORT" and pipeline_direction == "SHORT"
    aligned = both_long or both_short

    if not hp_result or hp_bias in ("WATCH", "SOH"):
        verdict = "NO_SIGNAL"
    elif aligned and hp_conf >= 0.70:
        verdict = "HIGH_CONVICTION"
    elif aligned:
        verdict = "WEAK"
    elif pipeline_direction == "HOLD" or pipeline_decision is None:
        verdict = "HP_ONLY"
    else:
        verdict = "DIVERGENT"

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "verdict": verdict,
        "aligned": aligned,
        "hp_bias": hp_bias,
        "hp_confidence": hp_conf,
        "hp_pattern": hp_result.pattern if hp_result else None,
        "hp_trigger": hp_result.trigger_price if hp_result else None,
        "pipeline_direction": pipeline_direction,
        "pipeline_conviction": pipeline_decision.get("conviction") if pipeline_decision else None,
        "hp_signal": hp_result.__dict__ if hp_result else None,
    }
