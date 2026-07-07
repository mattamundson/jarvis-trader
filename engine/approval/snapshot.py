"""Serialize pipeline results for durable pending-approval storage."""

from __future__ import annotations

import json
from typing import Any, Dict


def pipeline_result_for_approval_snapshot(result: dict) -> dict:
    """
    Return a JSON-round-trippable dict for SQLite storage.

    Uses json.dumps(default=str) so datetimes and odd types become strings.
    """
    keys = (
        "trade_decision",
        "risk_decision",
        "fund_decision",
        "debate_result",
        "final_action",
        "final_quantity",
        "requires_human",
        "summary",
        "errors",
        "analyst_reports",
        "confidence",
        "boosted_confidence",
        "raw_confidence",
        "confidence_threshold",
    )
    snap: Dict[str, Any] = {k: result.get(k) for k in keys}
    ar = result.get("analyst_reports") or {}
    tech = ar.get("technical") if isinstance(ar, dict) else None
    if tech is not None:
        snap["technical"] = tech
    return json.loads(json.dumps(snap, default=str))


def entry_price_from_snapshot(snap: dict) -> float | None:
    """Best-effort entry price for paper open from stored snapshot."""
    td = snap.get("trade_decision") or {}
    if not isinstance(td, dict):
        td = {}
    for key in ("limit_price", "stop_price"):
        v = td.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    tech = snap.get("technical") or {}
    if isinstance(tech, dict):
        v = tech.get("current_price")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None
