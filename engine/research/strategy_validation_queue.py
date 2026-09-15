"""Read-only strategy validation queue helpers.

The queue turns repo-consolidation evidence into an execution order for research.
It does not route orders, mutate config, or promote strategies.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

QUEUE_PATH = Path(__file__).with_name("strategy_validation_queue.json")
REQUIRED_PROMOTION_GATES = (
    "hypothesis",
    "data_contract",
    "backtest",
    "fees_slippage",
    "walk_forward",
    "parameter_stability",
    "regime_split",
    "monte_carlo_path_risk",
    "paper_shadow",
    "human_approval",
)
TERMINAL_NON_PROMOTABLE_STATES = {"blocked", "rejected", "halted"}


def load_queue(path: str | Path = QUEUE_PATH) -> dict[str, Any]:
    """Load the committed validation queue and fail on structural problems."""
    queue = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate_queue(queue)
    if problems:
        raise ValueError(
            "strategy_validation_queue is invalid:\n  - " + "\n  - ".join(problems)
        )
    return queue


def validate_queue(queue: dict[str, Any]) -> list[str]:
    """Return structural/promotion-safety problems, if any."""
    problems: list[str] = []
    if not isinstance(queue, dict):
        return ["queue is not an object"]
    items = queue.get("items")
    if not isinstance(items, list) or not items:
        return ["items must be a non-empty list"]
    required_gates = list(queue.get("promotion_required_gates") or [])
    if required_gates != list(REQUIRED_PROMOTION_GATES):
        problems.append("promotion_required_gates changed from canonical order")
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id") or "<missing>"
        if item_id in seen:
            problems.append(f"duplicate item id {item_id}")
        seen.add(item_id)
        for field in ("id", "source", "state", "next_step", "promotion_gates"):
            if not item.get(field):
                problems.append(f"{item_id}: missing {field}")
        gates = item.get("promotion_gates") or {}
        missing = set(REQUIRED_PROMOTION_GATES) - set(gates)
        extra = set(gates) - set(REQUIRED_PROMOTION_GATES)
        if missing:
            problems.append(f"{item_id}: missing gates {sorted(missing)}")
        if extra:
            problems.append(f"{item_id}: unknown gates {sorted(extra)}")
        if item.get("may_route_orders") is not False:
            problems.append(f"{item_id}: may_route_orders must be false in research queue")
        if item.get("state") == "promotion_candidate" and not all(gates.get(g) is True for g in REQUIRED_PROMOTION_GATES):
            problems.append(f"{item_id}: promotion_candidate without all gates true")
    return problems


def next_actionable_items(queue: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return non-terminal research items ordered by priority."""
    q = queue or load_queue()
    items = [i for i in q["items"] if i.get("state") not in TERMINAL_NON_PROMOTABLE_STATES]
    return sorted(items, key=lambda i: int(i.get("priority", 999)))


def promotion_ready(item: dict[str, Any]) -> bool:
    """True only when every required gate is true and state is promotion_candidate."""
    gates = item.get("promotion_gates") or {}
    return item.get("state") == "promotion_candidate" and all(gates.get(g) is True for g in REQUIRED_PROMOTION_GATES)
