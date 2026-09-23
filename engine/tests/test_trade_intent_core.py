from __future__ import annotations

import pytest

from trade_intents.core import TradeIntentError, compute_trade_intent_preview


def test_small_account_can_size_one_mes_contract_with_half_percent_risk() -> None:
    preview = compute_trade_intent_preview(
        symbol="MES",
        direction="BUY",
        order_type="MARKET",
        entry_price=6500,
        stop_loss=6498,
        take_profit=6504,
        account_equity=3000,
        max_risk_fraction=0.005,
        max_trade_loss_usd=50,
        max_contracts=2,
    )
    assert preview.risk_budget_usd == pytest.approx(15)
    assert preview.risk_usd_per_unit == pytest.approx(10)
    assert preview.final_quantity == 1
    assert preview.final_risk_usd == pytest.approx(10)
    assert preview.final_risk_fraction == pytest.approx(10 / 3000)
    assert preview.reward_risk == pytest.approx(2)
    assert preview.can_submit is True


def test_risk_budget_can_legitimately_produce_zero_quantity() -> None:
    preview = compute_trade_intent_preview(
        symbol="MES",
        direction="BUY",
        order_type="MARKET",
        entry_price=6500,
        stop_loss=6490,
        take_profit=6520,
        account_equity=3000,
        max_risk_fraction=0.005,
        max_trade_loss_usd=50,
        max_contracts=2,
    )
    assert preview.risk_usd_per_unit == pytest.approx(50)
    assert preview.risk_budget_usd == pytest.approx(15)
    assert preview.final_quantity == 0
    assert preview.can_submit is False
    assert "cannot support one" in (preview.blocking_reason or "")


def test_requested_quantity_is_ceiling_not_authority() -> None:
    preview = compute_trade_intent_preview(
        symbol="MES",
        direction="BUY",
        order_type="LIMIT",
        entry_price=6500,
        stop_loss=6499,
        take_profit=6502,
        account_equity=10_000,
        max_risk_fraction=0.005,
        max_trade_loss_usd=50,
        requested_quantity=20,
        max_contracts=2,
    )
    assert preview.max_quantity_by_risk == 10
    assert preview.final_quantity == 2


def test_existing_dollar_loss_ceiling_caps_risk_budget() -> None:
    preview = compute_trade_intent_preview(
        symbol="MES",
        direction="BUY",
        order_type="MARKET",
        entry_price=6500,
        stop_loss=6499,
        take_profit=6502,
        account_equity=100_000,
        max_risk_fraction=0.01,
        max_trade_loss_usd=50,
        max_contracts=20,
    )
    assert preview.risk_budget_usd == pytest.approx(50)
    assert preview.final_quantity == 10
    assert preview.final_risk_usd == pytest.approx(50)


def test_sell_geometry_is_directionally_validated() -> None:
    preview = compute_trade_intent_preview(
        symbol="MES",
        direction="SELL",
        order_type="LIMIT",
        entry_price=6500,
        stop_loss=6502,
        take_profit=6496,
        account_equity=3000,
    )
    assert preview.reward_risk == pytest.approx(2)

    with pytest.raises(TradeIntentError, match="SELL stop_loss must be above"):
        compute_trade_intent_preview(
            symbol="MES",
            direction="SELL",
            order_type="LIMIT",
            entry_price=6500,
            stop_loss=6499,
            take_profit=6496,
            account_equity=3000,
        )


def test_risk_fraction_hard_caps_at_one_percent() -> None:
    with pytest.raises(TradeIntentError, match="0.01"):
        compute_trade_intent_preview(
            symbol="MES",
            direction="BUY",
            order_type="MARKET",
            entry_price=6500,
            stop_loss=6498,
            take_profit=6504,
            account_equity=3000,
            max_risk_fraction=0.011,
        )


def test_unknown_multiplier_fails_closed() -> None:
    with pytest.raises(ValueError, match="No contract multiplier"):
        compute_trade_intent_preview(
            symbol="UNKNOWN_FUTURE",
            direction="BUY",
            order_type="MARKET",
            entry_price=100,
            stop_loss=99,
            take_profit=102,
            account_equity=3000,
        )
