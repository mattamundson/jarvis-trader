"""Emit schema-conformant gate-v2 verdicts into the RESEARCH namespace.

Research verdicts (from the X-bookmark edge scan) are kept OUT of
``engine/data/gate_v2_verdicts/`` — the production authorization dir that
``gate_v2_policy.is_strategy_authorized`` reads — so a research FAIL can never be
mistaken for a routing signal (the 2026-06-06 stale-verdict incident lesson). They
live in ``engine/data/research_verdicts/`` and are surfaced read-only by
``GET /strategy/research-candidates``.

The verdict body conforms to ``backtest.verdict_schema.VerdictSchema`` (``extra="allow"``)
plus three research-only fields: ``strategy``, ``strategy_class``, ``provenance``,
``class_note``. Metrics are pulled straight from the ``validate()`` report — no recompute,
no drift from what the backtest actually scored.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def research_verdicts_dir(base: Path | None = None) -> Path:
    """Engine-relative research-verdicts dir (same convention as the router).

    This module lives in ``engine/backtest/``, so ``parent.parent`` is the engine
    root — mirrors ``strategy_ledger_router._verdicts_dir``. Writing here means the
    files land in whichever checkout the runner ran from (committed on the branch;
    served by the live engine from the main checkout).
    """
    root = base or Path(__file__).resolve().parent.parent
    d = root / "data" / "research_verdicts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _num(v: Any) -> float | None:
    """Coerce to a JSON-safe float; map inf/nan → None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def metrics_from_report(report: dict) -> dict:
    """Extract the four headline gate metrics from a ``validate()`` report."""
    def _get(d: Any, *keys: str) -> Any:
        for k in keys:
            d = d.get(k) if isinstance(d, dict) else None
        return d

    return {
        "pf_ci_lower": _num(_get(report, "bootstrap_block", "pf_ci_95_low")),
        "p_edge": _num(_get(report, "bootstrap_iid", "p_positive_edge")),
        "mc_95th_dd_pct": _num(_get(report, "drawdown_mc", "mc_95th")),
        "dsr": _num(_get(report, "deflated_sharpe", "dsr")),
    }


def write_research_verdict(
    *,
    strategy: str,
    symbol: str,
    family: str,
    rank: int,
    report: dict,
    verdict: dict,
    strategy_class: str,
    provenance: dict,
    class_note: str,
    extra: dict | None = None,
    base: Path | None = None,
) -> Path:
    """Assemble + write one research verdict JSON. Returns the path written."""
    body: dict[str, Any] = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "strategy": strategy,
        "strategy_class": strategy_class,
        "verdict": verdict.get("verdict"),
        "passed_via": verdict.get("passed_via"),
        "core_verdict": verdict.get("core_verdict"),
        "alt_verdict": verdict.get("alt_verdict"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate_v2_metrics": metrics_from_report(report),
        "gate_v2": {
            "verdict": verdict.get("verdict"),
            "passed_via": verdict.get("passed_via"),
            "core_verdict": verdict.get("core_verdict"),
            "alt_verdict": verdict.get("alt_verdict"),
            "reasons": verdict.get("reasons"),
        },
        "provenance": provenance,
        "class_note": class_note,
    }
    if extra:
        body.update(extra)
    out = research_verdicts_dir(base) / f"{symbol}_{family}_rank{rank}.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
    return out
