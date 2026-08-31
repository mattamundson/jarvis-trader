"""Tests for research-only dashboard trade-intent contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest.realtime_trade_intent import TradeIntent, TradeIntentError, preview_trade_risk


def _intent(**overrides) -> TradeIntent:
    created = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    data = dict(
        intent_id="intent-1",
        idempotency_key="key-1",
        symbol="MES",
        side="BUY",
        entry_type="MARKETABLE_LIMIT",
        reference_price=6500.0,
        stop_price=6498.0,
        target_price=6504.0,
        max_risk_fraction=0.005,
        created_at=created,
        expires_at=created + timedelta(minutes=5),
        requested_quantity=None,
        contract_multiplier=5.0,
    )
    data.update(overrides)
    return TradeIntent(**data)


def test_buy_geometry_and_risk_preview() -> None:
    intent = _intent()
    preview = preview_trade_risk(intent, account_equity=3000.0)
    # 2 points * $5/point = $10 risk per MES; $15 risk budget => 1 contract.
    assert preview.risk_budget == pytest.approx(15.0)
    assert preview.risk_per_unit == pytest.approx(10.0)
    assert preview.engine_max_quantity == 1
    assert preview.approved_preview_quantity == 1
    assert preview.planned_risk_dollars == pytest.approx(10.0)
    assert preview.planned_risk_fraction == pytest.approx(10.0 / 3000.0)
    assert preview.planned_rr == pytest.approx(2.0)


def test_requested_quantity_is_reduced_to_engine_preview_cap() -> None:
    intent = _intent(requested_quantity=4)
    preview = preview_trade_risk(intent, account_equity=3000.0)
    assert preview.approved_preview_quantity == 1
    assert preview.quantity_was_reduced is True


def test_sell_geometry_is_directionally_validated() -> None:
    intent = _intent(
        side="SELL",
        reference_price=6500.0,
        stop_price=6502.0,
        target_price=6496.0,
    )
    assert intent.planned_rr == pytest.approx(2.0)

    with pytest.raises(TradeIntentError, match="SELL stop_price"):
        _intent(side="SELL", stop_price=6499.0, target_price=6496.0)


def test_buy_stop_or_target_on_wrong_side_fails_closed() -> None:
    with pytest.raises(TradeIntentError, match="BUY stop_price"):
        _intent(stop_price=6501.0)
    with pytest.raises(TradeIntentError, match="BUY target_price"):
        _intent(target_price=6499.0)


def test_limit_intent_requires_limit_price() -> None:
    with pytest.raises(TradeIntentError, match="requires limit_price"):
        _intent(entry_type="LIMIT")
    intent = _intent(entry_type="LIMIT", limit_price=6499.75)
    assert intent.limit_price == pytest.approx(6499.75)


def test_expiry_and_timezone_are_fail_closed() -> None:
    intent = _intent()
    assert intent.is_expired(intent.expires_at) is True

    created_naive = datetime(2026, 8, 31, 14, 0)
    with pytest.raises(TradeIntentError, match="timezone-aware"):
        _intent(created_at=created_naive)


def test_account_too_small_for_one_unit_returns_zero_preview_size() -> None:
    intent = _intent(max_risk_fraction=0.001)
    preview = preview_trade_risk(intent, account_equity=3000.0)
    assert preview.risk_budget == pytest.approx(3.0)
    assert preview.engine_max_quantity == 0
    assert preview.approved_preview_quantity == 0
    assert preview.planned_risk_dollars == 0.0
