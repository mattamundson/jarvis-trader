"""E6 -- end-to-end safety-gate PRECEDENCE / fail-fast characterization tests.

The existing safety tests prove each gate rejects in isolation, but they all use
*valid* orders -- so none proves the ORDER of the gates. ``check_order`` runs its
checks sequentially and returns on the FIRST failure (safety_layer.py:1206-1220),
which means the precedence is itself a safety contract: the kill switch must be
gate #1, and the cheap go/no-go gates (live-trading, human-approval) must precede
the order-sizing gates. A refactor that reordered the list would pass every
existing test yet silently change which rejection a blocked order reports -- and,
worse, could let a sizing check run (or its side effects fire) before the kill
switch is even consulted.

These tests pin that precedence by submitting orders that violate MULTIPLE gates
at once and asserting WHICH rejection wins. They are characterization tests: they
assert current, intended behavior so a future reorder breaks the build.

Verified-against-source order (safety_layer.py:1206-1214):
    1 kill_switch  2 gating_conditions  3 daily_loss  4 drawdown
    5 order_value  6 trade_loss  7 contract_limits  8 stark_tpo
"""

from __future__ import annotations

from risk.safety_layer import KillSwitchReason, OrderRequest, SafetyLayer


def _grossly_invalid_order() -> OrderRequest:
    """An order that violates BOTH the single-order-value gate (#5) and the
    contract-limit gate (#7): qty 99 >> max 2, value $1M >> max $5k."""
    return OrderRequest(
        symbol="MES",
        quantity=99,
        order_type="market",
        estimated_value=1_000_000.0,
    )


def _live_enabled(mock_settings):
    """Open the two go/no-go gates so a test can reach the sizing gates."""
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    return mock_settings


# -- kill switch is gate #1 (precedes everything) -----------------------------

def test_kill_switch_precedes_gating_conditions(mock_safety_layer):
    """KS active + live-trading-disabled (default fixture): the rejection must be
    the KILL SWITCH, not the live-trading gate -- proving gate #1 wins over #2."""
    safety = mock_safety_layer  # LIVE_TRADING_ENABLED=False by fixture default
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "halt")

    result = safety.check_order(
        OrderRequest(symbol="MES", quantity=1, order_type="market",
                     estimated_value=1000.0),
        100_000.0,
    )
    assert result.approved is False
    assert "Kill switch" in result.rejection_reason
    assert "Live trading" not in result.rejection_reason


def test_kill_switch_precedes_size_gates(mock_settings):
    """The single most-broken-world order: KS active AND grossly oversized.
    First confirm the order is independently size-invalid; then confirm that with
    the kill switch on, the KS rejection short-circuits BEFORE any sizing gate."""
    _live_enabled(mock_settings)
    order = _grossly_invalid_order()

    # Without the kill switch, the same order is rejected by a SIZING gate.
    baseline = SafetyLayer(mock_settings).check_order(order, 100_000.0)
    assert baseline.approved is False
    assert "exceeds max" in baseline.rejection_reason  # order-value / contract gate

    # With the kill switch active, the KS rejection must win (gate #1 short-circuit).
    safety = SafetyLayer(mock_settings)
    safety.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT, "circuit breaker")
    killed = safety.check_order(order, 100_000.0)
    assert killed.approved is False
    assert "Kill switch" in killed.rejection_reason
    assert "exceeds max" not in killed.rejection_reason


# -- the go/no-go gates (#2) precede the sizing gates (fail-fast) --------------

def test_live_trading_gate_precedes_size_gates(mock_settings):
    """Live trading disabled + grossly invalid order -> the live-trading gate
    wins over the sizing gates (gate #2 before #5/#7)."""
    mock_settings.LIVE_TRADING_ENABLED = False
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    result = SafetyLayer(mock_settings).check_order(_grossly_invalid_order(), 100_000.0)
    assert result.approved is False
    assert "Live trading is disabled" in result.rejection_reason
    assert "exceeds max" not in result.rejection_reason


def test_human_approval_gate_precedes_size_gates(mock_settings):
    """Live trading enabled but human-approval required + grossly invalid order
    -> the human-approval gate wins over the sizing gates."""
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = True
    result = SafetyLayer(mock_settings).check_order(_grossly_invalid_order(), 100_000.0)
    assert result.approved is False
    assert "Human approval required" in result.rejection_reason
    assert "exceeds max" not in result.rejection_reason


# -- fail-fast: a clean order with both go/no-go gates open is APPROVED --------

def test_clean_order_passes_all_gates_when_open(mock_settings):
    """Control: with KS off, live trading on, approval off, a small valid order
    clears every gate. Guards against a precedence test that 'passes' only
    because the order is always rejected for some unrelated reason."""
    _live_enabled(mock_settings)
    result = SafetyLayer(mock_settings).check_order(
        OrderRequest(symbol="MES", quantity=1, order_type="market",
                     estimated_value=1000.0),
        100_000.0,
    )
    assert result.approved is True
