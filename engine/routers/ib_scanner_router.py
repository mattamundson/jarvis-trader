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

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

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
