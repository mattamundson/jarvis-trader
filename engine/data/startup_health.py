"""
Startup health checks for critical external dependencies.

Run at engine startup to validate required services before the trading
pipeline depends on them. Failures are logged and reported, but do not
block engine startup unless explicitly configured.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_TV_CLI = Path(__file__).resolve().parent.parent.parent / "tradingview-mcp" / "src" / "cli" / "index.js"


def _run(cmd: List[str], timeout: int = 20) -> Dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        return {}
    except Exception as exc:
        logger.warning("startup health command failed: %s", exc)
        return {}


def check_tradingview_cdp() -> Dict[str, Optional[object]]:
    if not _TV_CLI.exists():
        return {"ok": False, "error": "cli_missing", "path": str(_TV_CLI)}

    status = _run(["node", str(_TV_CLI), "status"])
    ok = bool(status.get("success") and status.get("cdp_connected"))
    return {
        "ok": ok,
        "error": None if ok else "cdp_unavailable",
        "symbol": status.get("chart_symbol"),
        "resolution": status.get("chart_resolution"),
        "path": str(_TV_CLI),
    }


def run_startup_checks() -> List[Dict[str, Optional[object]]]:
    checks = [
        ("tradingview_cdp", check_tradingview_cdp),
    ]
    results: List[Dict[str, Optional[object]]] = []
    for name, check in checks:
        try:
            result = check()
        except Exception as exc:
            logger.warning("startup check %s failed: %s", name, exc)
            result = {"ok": False, "error": str(exc)}
        results.append({"check": name, **result})
    return results
