"""
MarketScanner shim — bridges pipeline_router manual-scan endpoint
to the real SignalScanner in scanner/signal_scanner.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MarketScanner:
    """Thin wrapper so pipeline_router /scheduler/manual-scan works."""

    async def scan_all_markets(self) -> dict:
        """
        Trigger a manual scan via the live SignalScanner instance
        registered via routers.scanner_router.inject_dependencies().
        """
        try:
            from routers.scanner_router import _signal_scanner as scanner  # noqa: PLC0415

            if scanner is None:
                return {
                    "status": "scanner_unavailable",
                    "message": "SignalScanner not initialised — check engine startup logs",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

            if not getattr(scanner, "_active", False):
                return {
                    "status": "scanner_paused",
                    "message": "Scanner is paused",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

            # Run one scan pass immediately (bypasses market-hours gate intentionally
            # since this is a manual trigger — operator chose to run it)
            await scanner._run_scan()
            status = scanner.status()

            return {
                "status": "ok",
                "symbols": status.get("symbols", []),
                "total_scans": status.get("total_scans"),
                "approvals_created": status.get("approvals_created"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as exc:
            logger.error(f"[MarketScanner] scan_all_markets failed: {exc}", exc_info=True)
            return {
                "status": "error",
                "message": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
