"""Tests for the unified multi-channel signal broadcaster.

Covers field extraction (correct pipeline keys), per-channel fan-out, the
shared cooldown dedupe across call sites, partial-failure isolation, and the
HOLD/no-channel short-circuits.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from notifications import signal_broadcast as sb
from notifications.pipeline_alert_cooldown import reset_pipeline_alert_cooldown_for_tests


def _signal_result(action: str = "buy") -> dict:
    return {
        "final_action": action,
        "boosted_confidence": 0.82,
        "trade_decision": {
            "entry_price": 5000.25,
            "stop_price": 4990.0,
            "target_price": 5020.0,
            "reasoning": "STC cross + auction acceptance above VAH",
        },
        "fund_decision": {"human_approval_required": False},
        "risk_decision": {"approved": True},
    }


# --- extract_signal_fields ---------------------------------------------------


def test_extract_reads_correct_pipeline_keys() -> None:
    f = sb.extract_signal_fields("MES", _signal_result("buy"))
    assert f.label == "LONG"
    assert f.confidence == pytest.approx(0.82)
    assert f.entry_price == pytest.approx(5000.25)
    assert f.stop_price == pytest.approx(4990.0)
    assert f.target_price == pytest.approx(5020.0)
    # R:R computed from entry/stop/target when not provided directly.
    assert f.rr_ratio == pytest.approx(round(abs(5020.0 - 5000.25) / abs(5000.25 - 4990.0), 2))
    assert "STC cross" in f.reason


def test_extract_sell_maps_to_short() -> None:
    f = sb.extract_signal_fields("MCL", _signal_result("sell"))
    assert f.label == "SHORT"


# --- broadcast_signal orchestration -----------------------------------------


@pytest.mark.asyncio
async def test_broadcast_fans_out_and_cooldown_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_pipeline_alert_cooldown_for_tests()
    monkeypatch.setattr(sb.settings, "ALERT_COOLDOWN_MINUTES", 60, raising=False)

    with patch.object(sb, "_any_channel_enabled", return_value=True), \
        patch.object(sb, "_send_telegram", new=AsyncMock(return_value=True)) as tg, \
        patch.object(sb, "_send_discord", new=AsyncMock(return_value=True)) as dc, \
        patch.object(sb, "_send_whatsapp", new=AsyncMock(return_value=None)) as wa, \
        patch.object(sb, "_send_windows_toast", new=AsyncMock(return_value=None)) as wt:

        first = await sb.broadcast_signal("MES", _signal_result("buy"), source="pipeline")
        # Second call for same symbol inside cooldown → fully suppressed.
        second = await sb.broadcast_signal("MES", _signal_result("buy"), source="scheduler")

    assert set(first["sent"]) == {"telegram", "discord"}
    assert set(first["skipped"]) == {"whatsapp", "windows_toast"}
    assert first["failed"] == []
    # Each channel called exactly once (cooldown blocked the 2nd broadcast).
    assert tg.await_count == 1 and dc.await_count == 1
    assert wa.await_count == 1 and wt.await_count == 1
    assert second["suppressed"] == "cooldown"


@pytest.mark.asyncio
async def test_broadcast_one_channel_failure_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_pipeline_alert_cooldown_for_tests()
    monkeypatch.setattr(sb.settings, "ALERT_COOLDOWN_MINUTES", 60, raising=False)

    with patch.object(sb, "_any_channel_enabled", return_value=True), \
        patch.object(sb, "_send_telegram", new=AsyncMock(side_effect=RuntimeError("boom"))), \
        patch.object(sb, "_send_discord", new=AsyncMock(return_value=True)), \
        patch.object(sb, "_send_whatsapp", new=AsyncMock(return_value=False)), \
        patch.object(sb, "_send_windows_toast", new=AsyncMock(return_value=None)):

        summary = await sb.broadcast_signal("MGC", _signal_result("buy"), source="pipeline")

    assert "discord" in summary["sent"]
    assert "telegram" in summary["failed"]
    assert "whatsapp" in summary["failed"]
    assert "windows_toast" in summary["skipped"]


@pytest.mark.asyncio
async def test_broadcast_skips_hold() -> None:
    reset_pipeline_alert_cooldown_for_tests()
    summary = await sb.broadcast_signal("MES", _signal_result("hold"), source="pipeline")
    assert summary["suppressed"] == "non_signal_action"
    assert summary["sent"] == []


@pytest.mark.asyncio
async def test_broadcast_suppressed_when_no_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_pipeline_alert_cooldown_for_tests()
    with patch.object(sb, "_any_channel_enabled", return_value=False):
        summary = await sb.broadcast_signal("MES", _signal_result("buy"), source="pipeline")
    assert summary["suppressed"] == "no_channel"


# --- DO_NOT_TRADE_SYMBOLS gate (halted instruments never notify) -------------


@pytest.mark.asyncio
async def test_broadcast_suppressed_for_do_not_trade_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCL/MNQ can still get a BUY/SELL final_action from the live agent
    pipeline (order execution is blocked separately in SafetyLayer), but a
    real notification implying an actionable signal must never go out."""
    reset_pipeline_alert_cooldown_for_tests()

    with patch.object(sb, "_any_channel_enabled", return_value=True), \
        patch.object(sb, "_send_telegram", new=AsyncMock(return_value=True)) as tg, \
        patch.object(sb, "_send_discord", new=AsyncMock(return_value=True)) as dc, \
        patch.object(sb, "_send_whatsapp", new=AsyncMock(return_value=True)) as wa, \
        patch.object(sb, "_send_windows_toast", new=AsyncMock(return_value=True)) as wt:

        mcl_summary = await sb.broadcast_signal("MCL", _signal_result("buy"), source="scheduler")
        mnq_summary = await sb.broadcast_signal("mnq", _signal_result("sell"), source="pipeline")

    assert mcl_summary["suppressed"] == "do_not_trade_symbol"
    assert mcl_summary["sent"] == []
    assert mnq_summary["suppressed"] == "do_not_trade_symbol"
    assert mnq_summary["sent"] == []
    # No channel sender was ever invoked for either halted symbol.
    tg.assert_not_awaited()
    dc.assert_not_awaited()
    wa.assert_not_awaited()
    wt.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_still_sends_for_active_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DO_NOT_TRADE_SYMBOLS gate must not suppress ACTIVE symbols (MES/MGC)."""
    reset_pipeline_alert_cooldown_for_tests()

    with patch.object(sb, "_any_channel_enabled", return_value=True), \
        patch.object(sb, "_send_telegram", new=AsyncMock(return_value=True)), \
        patch.object(sb, "_send_discord", new=AsyncMock(return_value=True)), \
        patch.object(sb, "_send_whatsapp", new=AsyncMock(return_value=None)), \
        patch.object(sb, "_send_windows_toast", new=AsyncMock(return_value=None)):

        summary = await sb.broadcast_signal("MGC", _signal_result("buy"), source="scheduler")

    assert summary["suppressed"] is None
    assert set(summary["sent"]) == {"telegram", "discord"}
