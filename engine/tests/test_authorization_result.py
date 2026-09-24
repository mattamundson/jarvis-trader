"""Tests for shared order-authorization result contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from approval.authorization import AuthorizationReason, kill_switch_active_from_status
from approval.service import (
    ApprovalFlowError,
    ensure_approval_allowed,
    evaluate_approval_allowed,
)
from routers import approval_queue_router


def _approval_row(symbol: str = "MES", *, stark_signal: str | None = None) -> dict:
    snapshot: dict[str, object] = {
        "data_provenance": {
            "last_bar_source": "ibkr",
            "serve_age_s": 12.0,
            "data_quality": "ok",
        }
    }
    if stark_signal is not None:
        snapshot["analyst_reports"] = {
            "technical": {
                "indicators": {
                    "stark_signal": stark_signal,
                }
            }
        }
    return {"symbol": symbol, "status": "pending", "pipeline_snapshot": snapshot}


def _approval_row_with_snapshot(symbol: str, snapshot: dict) -> dict:
    return {"symbol": symbol, "status": "pending", "pipeline_snapshot": snapshot}


def test_manual_approval_result_reports_feature_snapshot_blocked() -> None:
    with (
        patch("approval.service.approved_watchlist_symbols", return_value={"MES"}),
        patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "ok")),
    ):
        result = evaluate_approval_allowed(
            _approval_row_with_snapshot(
                "MES",
                {
                    "data_provenance": {
                        "last_bar_source": "ibkr",
                        "serve_age_s": 360.0,
                        "data_quality": "ok",
                    }
                },
            ),
            _safety_layer(),
        )

    assert result.allowed is False
    assert result.reason is AuthorizationReason.FEATURE_SNAPSHOT_BLOCKED
    assert result.context["symbol"] == "MES"
    assert result.context["feature_reasons"] == ["stale:market_bars"]


def test_manual_approval_exception_preserves_feature_snapshot_reason_code() -> None:
    with (
        patch("approval.service.approved_watchlist_symbols", return_value={"MES"}),
        patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "ok")),
    ):
        try:
            ensure_approval_allowed(_approval_row_with_snapshot("MES", {}), _safety_layer())
        except ApprovalFlowError as exc:
            err = exc
        else:
            raise AssertionError("expected approval to be refused")

    assert err.status_code == 409
    assert err.reason_code == AuthorizationReason.FEATURE_SNAPSHOT_BLOCKED.value
    assert err.context["feature_reasons"] == ["missing:market_bars"]


def _safety_layer(*, killed: bool = False, status_error: Exception | None = None) -> MagicMock:
    safety = MagicMock()
    if status_error is None:
        safety.get_status.return_value = {
            "is_killed": killed,
            "kill_switch_active": killed,
        }
    else:
        safety.get_status.side_effect = status_error
    safety.get_lockout_status.return_value = {"locked": False}
    return safety


def test_kill_switch_status_accepts_internal_and_public_keys() -> None:
    assert kill_switch_active_from_status({"is_killed": True}) is True
    assert kill_switch_active_from_status({"kill_switch_active": True}) is True
    assert kill_switch_active_from_status({"is_killed": False, "kill_switch_active": False}) is False


def test_manual_approval_result_reports_symbol_not_approved() -> None:
    with patch("approval.service.approved_watchlist_symbols", return_value=set()):
        result = evaluate_approval_allowed(_approval_row("MCL"), _safety_layer())

    assert result.allowed is False
    assert result.reason is AuthorizationReason.SYMBOL_NOT_APPROVED
    assert result.status_code == 400
    assert result.context["symbol"] == "MCL"
    assert "not on approved futures watchlist" in result.detail


def test_manual_approval_result_reports_strategy_not_authorized() -> None:
    with (
        patch("approval.service.approved_watchlist_symbols", return_value={"MCL"}),
        patch(
            "backtest.gate_v2_policy.is_strategy_authorized",
            return_value=(False, "paper_config enabled=False"),
        ),
    ):
        result = evaluate_approval_allowed(_approval_row("MCL"), _safety_layer())

    assert result.allowed is False
    assert result.reason is AuthorizationReason.STRATEGY_NOT_AUTHORIZED
    assert result.status_code == 409
    assert result.context == {
        "symbol": "MCL",
        "strategy_reason": "paper_config enabled=False",
    }
    assert "paper_config enabled=False" in result.detail


def test_manual_approval_result_reports_validation_only_strategy() -> None:
    with (
        patch("approval.service.approved_watchlist_symbols", return_value={"MES"}),
        patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "ok")),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", {"SHORT_GAP_FILL"}),
    ):
        result = evaluate_approval_allowed(
            _approval_row("MES", stark_signal="SHORT_GAP_FILL"),
            _safety_layer(),
        )

    assert result.allowed is False
    assert result.reason is AuthorizationReason.VALIDATION_ONLY_STRATEGY
    assert result.status_code == 409
    assert result.context["strategy"] == "SHORT_GAP_FILL"


def test_manual_approval_exception_preserves_detail_and_exposes_reason_code() -> None:
    with patch("approval.service.approved_watchlist_symbols", return_value={"MES"}):
        try:
            ensure_approval_allowed(_approval_row("MES"), _safety_layer(killed=True))
        except ApprovalFlowError as exc:
            err = exc
        else:
            raise AssertionError("expected approval to be refused")

    assert err.status_code == 409
    assert err.detail == "Kill switch active — cannot approve"
    assert err.reason_code == AuthorizationReason.KILL_SWITCH_ACTIVE.value
    assert err.context == {"symbol": "MES"}


def test_manual_approval_result_reports_stop_out_lockout() -> None:
    safety = _safety_layer()
    safety.get_lockout_status.return_value = {"locked": True, "remaining_minutes": 17}

    with (
        patch("approval.service.approved_watchlist_symbols", return_value={"MES"}),
        patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "ok")),
    ):
        result = evaluate_approval_allowed(_approval_row("MES"), safety)

    assert result.allowed is False
    assert result.reason is AuthorizationReason.STOP_OUT_LOCKOUT
    assert result.context == {"symbol": "MES", "remaining_minutes": 17}
    assert "17 more minutes" in result.detail


def test_approval_queue_result_reports_live_mode(monkeypatch) -> None:
    monkeypatch.setattr(approval_queue_router, "_get_live_trading_enabled", lambda: True)

    result = approval_queue_router._authorization_result_for_approve()

    assert result.allowed is False
    assert result.reason is AuthorizationReason.LIVE_TRADING_ENABLED
    assert result.status_code == 409
    assert "LIVE_TRADING_ENABLED=True" in result.detail


def test_approval_queue_result_reports_missing_safety_layer(monkeypatch) -> None:
    monkeypatch.setattr(approval_queue_router, "_get_live_trading_enabled", lambda: False)
    monkeypatch.setattr(approval_queue_router, "_safety_layer", None)

    result = approval_queue_router._authorization_result_for_approve()

    assert result.allowed is False
    assert result.reason is AuthorizationReason.SAFETY_LAYER_MISSING
    assert result.detail == "safety_layer not injected"


def test_approval_queue_result_reports_safety_status_error(monkeypatch) -> None:
    monkeypatch.setattr(approval_queue_router, "_get_live_trading_enabled", lambda: False)
    monkeypatch.setattr(
        approval_queue_router,
        "_safety_layer",
        _safety_layer(status_error=RuntimeError("db unavailable")),
    )

    result = approval_queue_router._authorization_result_for_approve()

    assert result.allowed is False
    assert result.reason is AuthorizationReason.SAFETY_STATUS_ERROR
    assert "db unavailable" in result.detail


def test_approval_queue_result_reports_kill_switch_alias(monkeypatch) -> None:
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": True}
    monkeypatch.setattr(approval_queue_router, "_get_live_trading_enabled", lambda: False)
    monkeypatch.setattr(approval_queue_router, "_safety_layer", safety)

    result = approval_queue_router._authorization_result_for_approve()

    assert result.allowed is False
    assert result.reason is AuthorizationReason.KILL_SWITCH_ACTIVE
    assert result.detail == "kill switch active"


def test_approval_queue_legacy_tuple_wrapper_stays_stable(monkeypatch) -> None:
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    monkeypatch.setattr(approval_queue_router, "_get_live_trading_enabled", lambda: False)
    monkeypatch.setattr(approval_queue_router, "_safety_layer", safety)

    assert approval_queue_router._safety_guard_for_approve() == (True, "ok")
