"""
JARVIS TRADER — Proactive Advisor Brief (Phase 5)
==================================================
Pure assembly of a "session brief" from the reasoning fields the pipeline ALREADY
produces. Given one or more ``pipeline_snapshot`` dicts (as stored on decisions /
pending approvals), this turns them into 1-3 concrete recommended actions, each
carrying:

  * ``symbol`` / ``action`` / ``confidence`` — what the pipeline decided,
  * ``why`` — a plain-English explanation assembled ONLY from existing
    ``reasoning`` fields (trade / risk / fund / debate / technical),
  * ``reasoning_available`` — False when the snapshot carried NO reasoning, in
    which case ``why`` says so honestly instead of inventing a narrative,
  * ``staleness`` — age of the underlying decision vs a freshness window,
  * ``data_degraded`` — True when the decision is stale, errored, or reasoning-less.

NEVER fabricates. A missing reasoning field becomes an explicit gap statement, not
a made-up rationale. Pure module: no engine imports, no I/O, deterministic when a
fixed ``now`` is supplied (mirrors ``data/provenance.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Up to this many recommended actions in a single brief.
DEFAULT_MAX_ACTIONS = 3

# A decision older than this (seconds) is flagged stale. 15 min ~ a trading
# session's "still current" window for a discretionary recommendation.
DEFAULT_STALE_AFTER_S = 900.0

# Actions that are not a live recommendation to do something.
_INERT_ACTIONS = frozenset({"hold", "", "none"})

# (snapshot key, human label) pairs, in the order they read in the "why".
# Every one is a field the pipeline already emits — nothing is invented.
_REASONING_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("trade_decision", "reasoning", "Trade"),
    ("risk_decision", "reasoning", "Risk"),
    ("fund_decision", "reasoning", "Fund"),
    ("debate_result", "bull_weakest_point", "Bull-case weakness"),
    ("debate_result", "bear_weakest_point", "Bear-case weakness"),
)


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(ts: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string to an aware UTC datetime, or None."""
    if not isinstance(ts, str) or not ts:
        return None
    raw = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_seconds(ts: Any, now: datetime) -> Optional[float]:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds()


def _technical_reasoning(snapshot: dict) -> Optional[str]:
    """Technical analyst reasoning lives under analyst_reports.technical (or a
    flattened ``technical`` key on trimmed approval snapshots)."""
    tech = snapshot.get("technical")
    if not isinstance(tech, dict):
        ar = snapshot.get("analyst_reports")
        tech = ar.get("technical") if isinstance(ar, dict) else None
    if isinstance(tech, dict):
        reasoning = tech.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()
    return None


def build_action(
    snapshot: Any,
    *,
    now: Optional[datetime] = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> Optional[dict]:
    """Turn ONE pipeline snapshot into a recommended-action dict, or None if the
    input is not a usable snapshot. Never fabricates reasoning."""
    if not isinstance(snapshot, dict):
        return None
    now = now or datetime.now(timezone.utc)

    symbol = snapshot.get("symbol") or "UNKNOWN"
    td = snapshot.get("trade_decision") if isinstance(snapshot.get("trade_decision"), dict) else {}
    action = str(snapshot.get("final_action") or td.get("action") or "hold").lower()

    confidence = _coerce_float(snapshot.get("boosted_confidence"))
    if confidence is None:
        fund = snapshot.get("fund_decision")
        if isinstance(fund, dict):
            confidence = _coerce_float(fund.get("final_conviction"))
    if confidence is None:
        confidence = _coerce_float(snapshot.get("confidence"))
    if confidence is None and isinstance(td, dict):
        confidence = _coerce_float(td.get("confidence"))

    # Assemble the "why" from EXISTING reasoning fields only.
    fragments: list[str] = []
    sources: list[str] = []
    for container_key, field, label in _REASONING_FIELDS:
        container = snapshot.get(container_key)
        if not isinstance(container, dict):
            continue
        text = container.get(field)
        if isinstance(text, str) and text.strip():
            fragments.append(f"{label}: {text.strip()}")
            sources.append(label)
    tech_reasoning = _technical_reasoning(snapshot)
    if tech_reasoning:
        fragments.append(f"Technical: {tech_reasoning}")
        sources.append("Technical")

    reasoning_available = bool(fragments)
    if reasoning_available:
        why = " | ".join(fragments)
    else:
        why = (
            "No reasoning captured for this decision — the pipeline snapshot did "
            "not populate any trade/risk/fund/debate/technical reasoning field. "
            "Not fabricating a rationale."
        )

    as_of = snapshot.get("completed_at") or snapshot.get("started_at")
    age = _age_seconds(as_of, now)
    is_stale = age is not None and age > stale_after_s
    unknown_age = age is None
    staleness = {
        "as_of": as_of if isinstance(as_of, str) else None,
        "age_seconds": age,
        "is_stale": is_stale,
        "unknown_age": unknown_age,
    }

    has_errors = bool(snapshot.get("errors"))
    data_degraded = has_errors or (not reasoning_available) or is_stale or unknown_age

    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "why": why,
        "reasoning_available": reasoning_available,
        "reasoning_sources": sources,
        "staleness": staleness,
        "data_degraded": data_degraded,
    }


def _action_sort_key(action: dict) -> tuple:
    conf = action.get("confidence")
    age = action.get("staleness", {}).get("age_seconds")
    return (
        action.get("action", "hold") in _INERT_ACTIONS,  # actionable first
        -(conf if conf is not None else 0.0),  # higher confidence first
        age if age is not None else float("inf"),  # fresher first, unknown last
    )


def build_session_brief(
    snapshots: Any,
    *,
    now: Optional[datetime] = None,
    max_actions: int = DEFAULT_MAX_ACTIONS,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    dedupe_by_symbol: bool = True,
) -> dict:
    """Assemble a session brief from newest-first pipeline snapshots.

    Returns ``{generated_at, actions, count, degraded, note}``. When there are no
    usable snapshots, ``actions`` is empty and ``note`` explains the gap — the
    brief is honest about having nothing to say rather than inventing content.
    """
    now = now or datetime.now(timezone.utc)
    generated_at = now.isoformat()
    max_actions = max(1, int(max_actions))

    if not isinstance(snapshots, (list, tuple)) or not snapshots:
        return {
            "generated_at": generated_at,
            "actions": [],
            "count": 0,
            "degraded": True,
            "note": "No recent pipeline snapshots available to build a brief.",
        }

    actions: list[dict] = []
    seen_symbols: set[str] = set()
    for snap in snapshots:
        built = build_action(snap, now=now, stale_after_s=stale_after_s)
        if built is None:
            continue
        if dedupe_by_symbol:
            sym = built["symbol"]
            if sym in seen_symbols:
                continue
            seen_symbols.add(sym)
        actions.append(built)

    actions.sort(key=_action_sort_key)
    actions = actions[:max_actions]

    degraded = (not actions) or any(a["data_degraded"] for a in actions)
    note = None
    if not actions:
        note = "No pipeline snapshots yielded a usable recommended action."

    return {
        "generated_at": generated_at,
        "actions": actions,
        "count": len(actions),
        "degraded": degraded,
        "note": note,
    }
