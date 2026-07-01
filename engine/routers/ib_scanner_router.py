"""
IB Market Scanner Routes
=========================
HTTP endpoints for on-demand IB Gateway scanner queries.
Discovers opportunities (top movers, unusual volume, breakouts) beyond
the MCL/MNQ watchlist without touching any order routing path.

Routes:
  GET  /ib-scanner/top-movers        — gainers + losers + unusual volume (parallel)
  GET  /ib-scanner/futures-movers    — futures hot-by-volume on GLOBEX
  GET  /ib-scanner/raw               — raw passthrough for advanced scan codes

All routes:
  - Require X-API-Key header (enforced by APIKeyMiddleware on the FastAPI app)
  - Return HTTP 501 when ENABLE_IB_SCANNER=0 (default)
  - Never trigger orders — read-only scanner queries only

Enable:
  Set ENABLE_IB_SCANNER=1 in engine/.env then restart the engine.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from analytics.screener_filters import (
    BarProvider,
    ScreenerFilters,
    screen_candidates,
)
from brokers.ib_scanner import (
    VALID_SCAN_CODES,
    is_ib_scanner_enabled,
    scan,
    scan_futures_movers,
    scan_top_movers,
)

logger = logging.getLogger("jarvis_trader.routers.ib_scanner")

router = APIRouter(prefix="/ib-scanner", tags=["ib-scanner"])


# ── Response models ───────────────────────────────────────────────────────────


class ScannerResult(BaseModel):
    """A single ranked scanner result."""

    rank: int
    symbol: str
    sec_type: str
    exchange: str
    contract_id: int | None = None
    last_price: float | None = None
    volume: float | None = None
    pct_change: float | None = None

    model_config = ConfigDict(from_attributes=True)


class TopMoversResponse(BaseModel):
    """Response from /ib-scanner/top-movers."""

    enabled: bool
    gainers: list[ScannerResult]
    losers: list[ScannerResult]
    unusual_volume: list[ScannerResult]
    note: str = (
        "IB scanner results are snapshots (not live streams). "
        "IB caches server-side for up to 30s; re-call every 60s for fresh data."
    )

    model_config = ConfigDict(from_attributes=True)


class RawScanResponse(BaseModel):
    """Response from /ib-scanner/raw."""

    scan_code: str
    instrument: str
    location_code: str
    n_results: int
    results: list[ScannerResult]
    note: str = (
        "IB scanner results are snapshots (not live streams). "
        "IB caches server-side for up to 30s; re-call every 60s for fresh data."
    )

    model_config = ConfigDict(from_attributes=True)


# ── Routes ────────────────────────────────────────────────────────────────────


def _assert_enabled() -> None:
    """Raise HTTP 501 when scanner is disabled (default)."""
    if not is_ib_scanner_enabled():
        raise HTTPException(
            status_code=501,
            detail=(
                "IB market scanner is disabled. "
                "Set ENABLE_IB_SCANNER=1 in engine/.env and restart to activate. "
                "Requires IB Gateway connected on paper port 4002."
            ),
        )


def _coerce_results(raw: list[dict]) -> list[ScannerResult]:
    """Convert raw dicts from ib_scanner.scan() into ScannerResult models."""
    out: list[ScannerResult] = []
    for item in raw:
        try:
            out.append(ScannerResult(**item))
        except Exception as exc:
            logger.debug("[IbScannerRouter] skipping malformed item: %s — %s", item, exc)
    return out


@router.get("/top-movers", response_model=TopMoversResponse)
async def get_top_movers() -> TopMoversResponse:
    """
    Return top gainers, losers, and unusual-volume stocks in parallel.

    Runs TOP_PERC_GAIN + TOP_PERC_LOSE + HOT_BY_VOLUME simultaneously
    against IB Gateway. Typical latency: 3-10 seconds.

    Returns HTTP 501 when ENABLE_IB_SCANNER=0 (default).
    Returns empty lists when IB Gateway is disconnected.
    """
    _assert_enabled()
    try:
        movers = await scan_top_movers()
        return TopMoversResponse(
            enabled=True,
            gainers=_coerce_results(movers.get("gainers", [])),
            losers=_coerce_results(movers.get("losers", [])),
            unusual_volume=_coerce_results(movers.get("unusual_volume", [])),
        )
    except Exception as exc:
        logger.error("[IbScannerRouter] top-movers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scanner error: {exc}") from exc


@router.get("/futures-movers", response_model=RawScanResponse)
async def get_futures_movers() -> RawScanResponse:
    """
    Return hot-by-volume futures contracts on GLOBEX.

    Uses FUT_HOT_BY_VOLUME scan against FUT.GLOBEX location.
    Requires futures market data subscriptions on the paper account.
    Returns an empty results list if the account is not subscribed.

    Returns HTTP 501 when ENABLE_IB_SCANNER=0 (default).
    """
    _assert_enabled()
    try:
        results = await scan_futures_movers()
        return RawScanResponse(
            scan_code="FUT_HOT_BY_VOLUME",
            instrument="FUT",
            location_code="FUT.GLOBEX",
            n_results=50,
            results=_coerce_results(results),
        )
    except Exception as exc:
        logger.error("[IbScannerRouter] futures-movers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scanner error: {exc}") from exc


@router.get("/raw", response_model=RawScanResponse)
async def get_raw_scan(
    scan_code: str = Query(..., description="IB scan code, e.g. TOP_PERC_GAIN"),
    instrument: str = Query("STK", description="Instrument type, e.g. STK or FUT.US"),
    location_code: str = Query("STK.US.MAJOR", description="IB location code"),
    n: int = Query(50, ge=1, le=50, description="Number of results (max 50)"),
) -> RawScanResponse:
    """
    Raw scanner passthrough for advanced use cases.

    Accepts any scan_code from the supported list. Returns HTTP 400 if the
    scan_code is not in the VALID_SCAN_CODES allowlist.

    Supported scan codes:
      Equities: TOP_PERC_GAIN, TOP_PERC_LOSE, HOT_BY_VOLUME, TOP_OPEN_PERC_GAIN,
                HIGH_OPEN_GAP, LOW_OPEN_GAP, MOST_ACTIVE, TOP_TRADE_RATE
      Futures:  FUT_HOT_BY_VOLUME, FUT_TOP_PERC_GAIN, FUT_TOP_PERC_LOSE

    Returns HTTP 501 when ENABLE_IB_SCANNER=0 (default).
    """
    _assert_enabled()
    if scan_code not in VALID_SCAN_CODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown scan_code '{scan_code}'. " f"Supported codes: {sorted(VALID_SCAN_CODES)}"
            ),
        )
    try:
        results = await scan(
            scan_code=scan_code,
            instrument=instrument,
            location_code=location_code,
            n_results=n,
        )
        return RawScanResponse(
            scan_code=scan_code,
            instrument=instrument,
            location_code=location_code,
            n_results=n,
            results=_coerce_results(results),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[IbScannerRouter] raw scan failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scanner error: {exc}") from exc


# ── Pine Screener filters (GreenStar2-style) ──────────────────────────────────
# Pipe the read-only IB scanner movers universe through the screener filter
# chain (analytics/screener_filters.py) to reduce a large mover list to a small
# set of real-time focus names. Read-only: never touches order routing.

_HISTORY_PERIOD = "2y"  # enough daily bars for the 200-SMA / 52-week Minervini criteria


class ScreenRequest(BaseModel):
    """Universe source + filter thresholds for POST /ib-scanner/screen.

    Any threshold left as ``null`` is not applied. Defaults mirror the
    GreenStar2 screenshot: xFrom50 in [0, 4], RVOL > 1, %fromLoD < 70, Chg% > 0.
    """

    scan_code: str = Field("TOP_PERC_GAIN", description="IB scan code for the universe")
    symbols: list[str] | None = Field(
        None, description="Explicit symbol list; bypasses the IB scanner when provided"
    )
    max_symbols: int = Field(25, ge=1, le=50, description="Cap on candidates screened")

    x_from_50_min: float | None = 0.0
    x_from_50_max: float | None = 4.0
    rvol_min: float | None = 1.0
    x_from_lod_max: float | None = 70.0
    chg_pct_min: float | None = 0.0
    chg_open_pct_min: float | None = None
    atr_pct_min: float | None = None
    atr_pct_max: float | None = None
    mm_min: int | None = None

    model_config = ConfigDict(extra="forbid")

    def to_filters(self) -> ScreenerFilters:
        return ScreenerFilters(
            x_from_50_min=self.x_from_50_min,
            x_from_50_max=self.x_from_50_max,
            rvol_min=self.rvol_min,
            x_from_lod_max=self.x_from_lod_max,
            chg_pct_min=self.chg_pct_min,
            chg_open_pct_min=self.chg_open_pct_min,
            atr_pct_min=self.atr_pct_min,
            atr_pct_max=self.atr_pct_max,
            mm_min=self.mm_min,
        )


class ScreenedRow(BaseModel):
    """One symbol's screener metrics plus its pass/fail verdict."""

    symbol: str | None = None
    last_price: float | None = None
    atr_pct: float | None = None
    rvol: float | None = None
    x_from_50: float | None = None
    x_from_lod_pct: float | None = None
    chg_pct: float | None = None
    chg_open_pct: float | None = None
    mm_score: int = 0
    bars_used: int = 0
    passed: bool = False
    reasons: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class ScreenResponse(BaseModel):
    """Response from POST /ib-scanner/screen."""

    enabled: bool
    universe_source: str
    total_candidates: int
    passed_count: int
    focus: list[ScreenedRow]
    rejected: list[ScreenedRow]
    note: str = (
        "Focus names pass every active filter, sorted by RVOL desc. Metrics are "
        "point-in-time (decision bar = latest daily bar). Daily bars fetched via "
        "yfinance; symbols without bars are skipped."
    )

    model_config = ConfigDict(from_attributes=True)


def _make_yfinance_provider(period: str) -> BarProvider:
    """Build a daily-bar provider backed by yfinance (lazy import, graceful)."""

    def _provider(symbol: str):  # pragma: no cover — network I/O
        import pandas as pd
        import yfinance as yf

        raw = yf.download(
            symbol, period=period, interval="1d", auto_adjust=True, progress=False
        )
        if raw is None or len(raw) == 0:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns=str.lower)
        cols = ["open", "high", "low", "close", "volume"]
        if not all(c in raw.columns for c in cols):
            return None
        return raw[cols].dropna()

    return _provider


async def _universe_symbols(req: ScreenRequest) -> list[str]:
    """Resolve the candidate symbol list from the request or the IB scanner."""
    if req.symbols:
        return list(dict.fromkeys(req.symbols))[: req.max_symbols]
    if req.scan_code not in VALID_SCAN_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scan_code '{req.scan_code}'. Supported: {sorted(VALID_SCAN_CODES)}",
        )
    rows = await scan(scan_code=req.scan_code, n_results=req.max_symbols)
    seen: list[str] = []
    for row in rows:
        sym = row.get("symbol")
        if sym and sym != "UNKNOWN" and sym not in seen:
            seen.append(sym)
    return seen[: req.max_symbols]


@router.post("/screen", response_model=ScreenResponse)
async def post_screen(req: ScreenRequest) -> ScreenResponse:
    """Screen an IB scanner movers universe with GreenStar2-style filters.

    Pulls the universe (``scan_code`` movers, or an explicit ``symbols`` list),
    fetches daily bars per candidate, computes the screener metrics, and returns
    the focus names that pass every active filter. Read-only — no order routing.

    Returns HTTP 501 when ENABLE_IB_SCANNER=0 unless an explicit ``symbols`` list
    is supplied (which needs no IB connection).
    """
    using_scanner = not req.symbols
    if using_scanner:
        _assert_enabled()
    try:
        symbols = await _universe_symbols(req)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[IbScannerRouter] screen universe resolve failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scanner error: {exc}") from exc

    if not symbols:
        return ScreenResponse(
            enabled=is_ib_scanner_enabled(),
            universe_source="symbols" if req.symbols else req.scan_code,
            total_candidates=0,
            passed_count=0,
            focus=[],
            rejected=[],
        )

    provider = _make_yfinance_provider(_HISTORY_PERIOD)
    filters = req.to_filters()
    try:
        # screen_candidates + yfinance fetches are blocking — run off the loop.
        results = await asyncio.to_thread(screen_candidates, symbols, provider, filters)
    except Exception as exc:
        logger.error("[IbScannerRouter] screen failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Screen error: {exc}") from exc

    rows = [ScreenedRow(**r.as_dict()) for r in results]
    focus = [r for r in rows if r.passed]
    rejected = [r for r in rows if not r.passed]
    return ScreenResponse(
        enabled=is_ib_scanner_enabled(),
        universe_source="symbols" if req.symbols else req.scan_code,
        total_candidates=len(rows),
        passed_count=len(focus),
        focus=focus,
        rejected=rejected,
    )
