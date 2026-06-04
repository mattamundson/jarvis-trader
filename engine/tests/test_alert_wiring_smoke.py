"""Smoke tests for AlertManager end-to-end alert wiring.

Verifies the full chain: check_and_alert() → threshold evaluation →
queue → worker → notify_fn called with the correct message.

Complements test_alert_manager_delivery_logging.py (which tests
delivery-result logging) by testing that thresholds actually fire
and the correct message body reaches the notify_fn.

Run:
    cd engine
    .venv/Scripts/python -m pytest tests/test_alert_wiring_smoke.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from risk.alert_manager import AlertManager
from risk.alert_thresholds import ALERT_THRESHOLDS


async def _drain(am: AlertManager) -> None:
    await asyncio.sleep(0)
    await am._alert_queue.join()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_am() -> tuple[AlertManager, list[str]]:
    """Return (manager, captured_messages)."""
    messages: list[str] = []

    async def notify(msg: str) -> bool:
        messages.append(msg)
        return True

    am = AlertManager(notify_fn=notify)
    return am, messages


# ---------------------------------------------------------------------------
# Daily loss thresholds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_loss_75pct_triggers_alert():
    """P&L at -1.5% fires the 75% daily-loss alert exactly once."""
    am, msgs = _make_am()
    am.start()

    threshold = ALERT_THRESHOLDS["daily_loss_75pct"]  # e.g. -0.015
    am.check_and_alert(
        daily_pnl=-150.0,
        daily_pnl_pct=threshold - 0.001,  # just below the threshold
        drawdown_pct=-0.01,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "DAILY LOSS 75%" in msgs[0]
    assert "Kill switch" in msgs[0]


@pytest.mark.asyncio
async def test_daily_loss_50pct_triggers_alert():
    """P&L between -1.0% and -1.5% fires the 50% warning (not 75%)."""
    am, msgs = _make_am()
    am.start()

    mid = (ALERT_THRESHOLDS["daily_loss_50pct"] + ALERT_THRESHOLDS["daily_loss_75pct"]) / 2
    am.check_and_alert(
        daily_pnl=-100.0,
        daily_pnl_pct=mid,
        drawdown_pct=-0.01,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "DAILY LOSS 50%" in msgs[0]


@pytest.mark.asyncio
async def test_no_loss_no_alert():
    """Flat P&L should fire no alerts."""
    am, msgs = _make_am()
    am.start()

    am.check_and_alert(
        daily_pnl=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert msgs == []


# ---------------------------------------------------------------------------
# Drawdown thresholds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drawdown_5pct_fires():
    """Drawdown at -5% fires the drawdown warning."""
    am, msgs = _make_am()
    am.start()

    threshold = ALERT_THRESHOLDS["drawdown_5pct"]  # -0.05
    am.check_and_alert(
        daily_pnl=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=threshold - 0.001,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "DRAWDOWN WARNING" in msgs[0]


@pytest.mark.asyncio
async def test_drawdown_10pct_fires_critical():
    """Drawdown at -10% fires the CRITICAL (not just warning) alert."""
    am, msgs = _make_am()
    am.start()

    threshold = ALERT_THRESHOLDS["drawdown_10pct"]  # -0.10
    am.check_and_alert(
        daily_pnl=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=threshold - 0.001,
        consecutive_losses=0,
        portfolio_equity=9_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "DRAWDOWN CRITICAL" in msgs[0]
    assert "imminent" in msgs[0].lower()


# ---------------------------------------------------------------------------
# Consecutive losses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_consecutive_losses_fires():
    """3 consecutive losses fires the scaling-factor alert."""
    am, msgs = _make_am()
    am.start()

    am.check_and_alert(
        daily_pnl=-30.0,
        daily_pnl_pct=-0.003,
        drawdown_pct=-0.01,
        consecutive_losses=3,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "3 CONSECUTIVE LOSSES" in msgs[0]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_threshold_fires_only_once_per_day():
    """check_and_alert called twice with the same condition → single alert."""
    am, msgs = _make_am()
    am.start()

    kwargs = {
        "daily_pnl": -150.0,
        "daily_pnl_pct": ALERT_THRESHOLDS["daily_loss_75pct"] - 0.001,
        "drawdown_pct": -0.01,
        "consecutive_losses": 0,
        "portfolio_equity": 10_000.0,
    }
    am.check_and_alert(**kwargs)
    am.check_and_alert(**kwargs)  # same state — should NOT fire again
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1, f"Expected 1 alert; got {len(msgs)}: {msgs}"


# ---------------------------------------------------------------------------
# No notify_fn configured — alert queued but not delivered (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_notify_fn_does_not_crash(caplog):
    """AlertManager with no notify_fn must not raise on check_and_alert."""
    import logging

    am = AlertManager(notify_fn=None)
    am.start()
    caplog.set_level(logging.WARNING, logger="risk.alert_manager")

    am.check_and_alert(
        daily_pnl=-150.0,
        daily_pnl_pct=ALERT_THRESHOLDS["daily_loss_75pct"] - 0.001,
        drawdown_pct=-0.01,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    dropped = [r for r in caplog.records if "alert dropped" in r.message]
    assert len(dropped) == 1


# ---------------------------------------------------------------------------
# Daily profit targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_target_hit_fires():
    """P&L at +5% triggers the daily-target-hit alert."""
    am, msgs = _make_am()
    am.start()

    threshold = ALERT_THRESHOLDS["daily_target_hit"]  # 0.05
    am.check_and_alert(
        daily_pnl=500.0,
        daily_pnl_pct=threshold + 0.001,
        drawdown_pct=0.0,
        consecutive_losses=0,
        portfolio_equity=10_000.0,
    )
    await _drain(am)
    await am.stop()

    assert len(msgs) == 1
    assert "DAILY TARGET HIT" in msgs[0]
