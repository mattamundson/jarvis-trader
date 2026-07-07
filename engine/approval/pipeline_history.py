"""Build ``pipeline_runs`` rows for scheduler and HTTP sources."""

from __future__ import annotations

import uuid
from typing import Any, Mapping


def pipeline_run_record_from_result(
    *,
    symbol: str,
    result: Mapping[str, Any],
    duration_ms: float,
    source: str,
    status: str = "completed",
    error_message: str | None = None,
) -> dict[str, Any]:
    """Shape a dict for ``DatabaseManager.insert_pipeline_run``."""
    action = result.get("final_action") or "hold"
    return {
        "run_id": str(uuid.uuid4())[:8],
        "symbol": symbol.upper(),
        "status": status,
        "source": source,
        "final_action": action,
        "final_quantity": int(result.get("final_quantity") or 0),
        "requires_human": bool(result.get("requires_human", False)),
        "summary": (result.get("summary") or "")[:500],
        "duration_ms": duration_ms,
        "error_message": error_message,
    }
