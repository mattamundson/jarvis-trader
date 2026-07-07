"""
IB Market Scanner — read-only opportunity discovery
====================================================
Wraps ib_async / ib_insync reqScannerData to surface top movers, unusual
volume, and breakout candidates beyond the MCL/MNQ watchlist.

SAFETY CONTRACT
---------------
- READ-ONLY: scanner queries only; never touches order routing.
- Paper port 4002 only; live port 4001 is blocked by IBGatewayManager.
- Default OFF: set ENABLE_IB_SCANNER=1 in engine/.env to activate.

Usage:
    from brokers.ib_scanner import scan_top_movers, is_ib_scanner_enabled

    if is_ib_scanner_enabled():
        result = await scan_top_movers()
        gainers = result["gainers"]
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── IB library availability ───────────────────────────────────────────────────
# Mirrors the same try/except pattern in execution/ib_gateway.py so the module
# loads cleanly whether or not ib_async is installed.

_IB_AVAILABLE = False
_IB_CLASS = None
_ScannerSubscription_CLASS = None

try:
    from ib_async import IB as _IB  # type: ignore[import]
    from ib_async import ScannerSubscription as _SS  # type: ignore[import]

    _IB_AVAILABLE = True
    _IB_CLASS = _IB
    _ScannerSubscription_CLASS = _SS
    logger.debug("ib_async loaded for scanner")
except ImportError:
    try:
        from ib_insync import IB as _IB  # type: ignore[import]  # noqa: F401
        from ib_insync import ScannerSubscription as _SS  # type: ignore[import]  # noqa: F401

        _IB_AVAILABLE = True
        _IB_CLASS = _IB
        _ScannerSubscription_CLASS = _SS
        logger.debug("ib_insync loaded for scanner (fallback)")
    except ImportError:
        logger.warning(
            "Neither ib_async nor ib_insync is installed — "
            "IBScanner will return empty results. "
            "Install with: pip install ib_async>=0.9.86"
        )

# ── Supported scan codes ──────────────────────────────────────────────────────
# Subset of IB's published scan codes. Futures scans depend on IB Gateway
# account permissions; some may return empty if not subscribed.

VALID_SCAN_CODES: frozenset[str] = frozenset(
    {
        "TOP_PERC_GAIN",
        "TOP_PERC_LOSE",
        "HOT_BY_VOLUME",
        "TOP_OPEN_PERC_GAIN",
        "HIGH_OPEN_GAP",
        "LOW_OPEN_GAP",
        "MOST_ACTIVE",
        "TOP_TRADE_RATE",
        "FUT_HOT_BY_VOLUME",
        "FUT_TOP_PERC_GAIN",
        "FUT_TOP_PERC_LOSE",
    }
)

# IB paper port — must stay paper-only, matching ib_gateway.py policy
_PAPER_PORT = 4002
_IB_HOST = "127.0.0.1"
# Client ID 10 — separate from engine's trading connections (client IDs 1-3)
_SCANNER_CLIENT_ID = 10
_DEFAULT_TIMEOUT_SECONDS = 10
_DEFAULT_N_RESULTS = 50


# ── Public API ────────────────────────────────────────────────────────────────


def is_ib_scanner_enabled() -> bool:
    """
    Read ENABLE_IB_SCANNER from the process environment (env-fresh check).

    Returns True only when the flag is explicitly set to "1". Default is OFF
    so that new deployments never silently connect to IB Gateway.
    """
    return os.environ.get("ENABLE_IB_SCANNER", "0").strip() == "1"


async def scan(
    scan_code: str,
    instrument: str = "STK",
    location_code: str = "STK.US.MAJOR",
    n_results: int = _DEFAULT_N_RESULTS,
) -> list[dict[str, Any]]:
    """
    Run a single one-shot IB scanner query and return ranked results.

    Parameters
    ----------
    scan_code : str
        One of VALID_SCAN_CODES (e.g. "TOP_PERC_GAIN").
    instrument : str
        IB instrument filter, e.g. "STK", "FUT.US".
    location_code : str
        IB location filter, e.g. "STK.US.MAJOR", "FUT.GLOBEX".
    n_results : int
        Maximum number of ranked results to request (max ~50 per IB limit).

    Returns
    -------
    list[dict]
        Each dict has: rank, symbol, sec_type, exchange, contract_id,
        last_price, volume (where available). Returns [] on timeout or error.

    Notes
    -----
    IB scanner results are ranked snapshots, not a live tick stream.
    IB caches scanner results for up to 30 seconds server-side. Rerun every
    60 seconds for fresh data — calling more frequently returns the same cache.
    """
    if not _IB_AVAILABLE or _IB_CLASS is None or _ScannerSubscription_CLASS is None:
        logger.warning("[IBScanner] ib_async/ib_insync not installed — scan() returning []")
        return []

    if scan_code not in VALID_SCAN_CODES:
        raise ValueError(
            f"Unknown scan_code '{scan_code}'. " f"Valid codes: {sorted(VALID_SCAN_CODES)}"
        )

    ib = _IB_CLASS()
    results: list[dict[str, Any]] = []

    try:
        await asyncio.wait_for(
            ib.connectAsync(
                host=_IB_HOST,
                port=_PAPER_PORT,
                clientId=_SCANNER_CLIENT_ID,
                readonly=True,
            ),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[IBScanner] Connection timeout to IB Gateway at %s:%d — is Gateway running?",
            _IB_HOST,
            _PAPER_PORT,
        )
        return []
    except Exception as exc:
        logger.warning("[IBScanner] Connection error: %s", exc)
        return []

    try:
        sub = _ScannerSubscription_CLASS(
            instrument=instrument,
            locationCode=location_code,
            scanCode=scan_code,
            numberOfRows=n_results,
        )

        scanner_data = await asyncio.wait_for(
            ib.reqScannerDataAsync(sub),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )

        for item in scanner_data or []:
            try:
                contract = item.contractDetails.contract if item.contractDetails else None
                results.append(
                    {
                        "rank": item.rank,
                        "symbol": contract.symbol if contract else "UNKNOWN",
                        "sec_type": contract.secType if contract else "",
                        "exchange": contract.exchange if contract else "",
                        "contract_id": contract.conId if contract else None,
                        "last_price": getattr(item, "lastPrice", None),
                        "volume": getattr(item, "volume", None),
                        "pct_change": getattr(item, "pctChange", None),
                    }
                )
            except Exception as item_exc:
                logger.debug("[IBScanner] Could not parse scanner item: %s", item_exc)

    except asyncio.TimeoutError:
        logger.warning(
            "[IBScanner] reqScannerData timed out after %ds for scan_code=%s",
            _DEFAULT_TIMEOUT_SECONDS,
            scan_code,
        )
    except Exception as exc:
        logger.error("[IBScanner] scan() error for %s: %s", scan_code, exc)
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    logger.info(
        "[IBScanner] scan_code=%s instrument=%s returned %d results",
        scan_code,
        instrument,
        len(results),
    )
    return results


async def scan_top_movers() -> dict[str, list[dict[str, Any]]]:
    """
    Convenience: run TOP_PERC_GAIN + TOP_PERC_LOSE + HOT_BY_VOLUME in parallel.

    Returns
    -------
    dict with keys:
        gainers          — TOP_PERC_GAIN, up to 50 results
        losers           — TOP_PERC_LOSE, up to 50 results
        unusual_volume   — HOT_BY_VOLUME, up to 50 results

    Notes
    -----
    IB scanner results are snapshots, not live streams. IB caches each scan
    server-side for up to 30 seconds. Re-call this function every 60 seconds
    or more for fresh data; sub-30s re-calls return the same cached snapshot.
    """
    gainers_task = asyncio.create_task(scan("TOP_PERC_GAIN"))
    losers_task = asyncio.create_task(scan("TOP_PERC_LOSE"))
    volume_task = asyncio.create_task(scan("HOT_BY_VOLUME"))

    gainers, losers, unusual_volume = await asyncio.gather(gainers_task, losers_task, volume_task)

    return {
        "gainers": gainers,
        "losers": losers,
        "unusual_volume": unusual_volume,
    }


async def scan_futures_movers() -> list[dict[str, Any]]:
    """
    Futures-specific volume movers (FUT_HOT_BY_VOLUME on GLOBEX).

    Requires IB Gateway account to have futures market data subscriptions.
    Returns [] if the scan code is not supported by the account.
    """
    return await scan(
        scan_code="FUT_HOT_BY_VOLUME",
        instrument="FUT",
        location_code="FUT.GLOBEX",
        n_results=_DEFAULT_N_RESULTS,
    )
