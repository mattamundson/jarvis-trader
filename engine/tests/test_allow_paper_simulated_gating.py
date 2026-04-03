"""ALLOW_PAPER_SIMULATED_ORDERS — explicit opt-in for SafetyLayer simulated paper path."""

from risk.safety_layer import OrderRequest, SafetyLayer


def test_opt_in_allows_check_order_when_live_off(mock_settings) -> None:
    mock_settings.LIVE_TRADING_ENABLED = False
    mock_settings.REQUIRE_HUMAN_APPROVAL = True
    mock_settings.PAPER_TRADING = True
    mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
    mock_settings.MAX_SINGLE_ORDER_VALUE = 100_000.0
    mock_settings.MAX_POSITION_SIZE_PCT = 1.0

    safety = SafetyLayer(mock_settings, pnl_monitor=None)
    order = OrderRequest(
        symbol="MES",
        quantity=1,
        order_type="market",
        estimated_value=1000.0,
    )
    result = safety.check_order(order, 100_000.0)
    assert result.approved is True


def test_allow_flag_does_not_bypass_human_when_live_on(mock_settings) -> None:
    """ALLOW_PAPER_SIMULATED_ORDERS must not weaken live + human gates."""
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = True
    mock_settings.PAPER_TRADING = True
    mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
    mock_settings.MAX_SINGLE_ORDER_VALUE = 100_000.0
    mock_settings.MAX_POSITION_SIZE_PCT = 1.0

    safety = SafetyLayer(mock_settings, pnl_monitor=None)
    order = OrderRequest(
        symbol="MES",
        quantity=1,
        order_type="market",
        estimated_value=1000.0,
    )
    result = safety.check_order(order, 100_000.0)
    assert result.approved is False
    assert result.rejection_reason and "Human approval required" in result.rejection_reason


def test_default_still_blocks_when_live_off(mock_settings) -> None:
    mock_settings.LIVE_TRADING_ENABLED = False
    mock_settings.REQUIRE_HUMAN_APPROVAL = True
    mock_settings.PAPER_TRADING = True
    mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = False

    safety = SafetyLayer(mock_settings, pnl_monitor=None)
    order = OrderRequest(
        symbol="MES",
        quantity=1,
        order_type="market",
        estimated_value=1000.0,
    )
    result = safety.check_order(order, 100_000.0)
    assert result.approved is False
    assert result.rejection_reason and "Live trading is disabled" in result.rejection_reason
