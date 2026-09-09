"""Governance ratchet for the active manual-order mutation spines.

This is intentionally source-level. It does not import the engine, connect a
broker, or execute an order. The goal is to prevent a third direct manual-order
HTTP authority from appearing while I-MIG-001 is unresolved.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
ROUTERS = {
    "orders": ENGINE_ROOT / "routers" / "orders_router.py",
    "trade_intents": ENGINE_ROOT / "routers" / "trade_intents_router.py",
}

EXPECTED_POST_ROUTES = {
    "orders": {"/orders/place"},
    "trade_intents": {
        "/trade-intents/preview",
        "/trade-intents/{intent_id}/submit",
    },
}


def _post_routes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "post"
                and isinstance(func.value, ast.Name)
                and func.value.id == "router"
            ):
                continue
            if not decorator.args:
                continue
            first = decorator.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                routes.add(first.value)
    return routes


def test_manual_order_mutation_route_inventory_is_explicit():
    observed = {name: _post_routes(path) for name, path in ROUTERS.items()}
    assert observed == EXPECTED_POST_ROUTES, (
        "Manual-order mutation authority changed. Do not add/rename a direct "
        "POST route until I-MIG-001 is updated with its source/target semantics, "
        "safety class, migration receipt, and retirement/disposition plan. "
        f"observed={observed!r} expected={EXPECTED_POST_ROUTES!r}"
    )


def test_trade_intent_router_remains_mounted_from_orders_router_during_current_baseline():
    """Pin the observed baseline; any containment/cutover must be explicit."""
    source = ROUTERS["orders"].read_text(encoding="utf-8")
    assert "router.include_router(trade_intents_router)" in source, (
        "TradeIntent mount changed. This may be a valid containment/cutover, "
        "but update I-CONT-001/I-MIG-001 and the required safety evidence in "
        "the same governed change rather than changing authority silently."
    )
