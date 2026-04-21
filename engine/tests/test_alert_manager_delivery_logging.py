"""Regression tests for AlertManager delivery-status logging.

Guards the 2026-04-21 fix where notify_fn returning False silently logged
"[AlertManager] Sent:" without checking the return value. See plan file
`~/.claude/plans/has-openclaw-been-deleted-misty-sketch.md` for context.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from risk.alert_manager import AlertManager


async def _drain(am: AlertManager) -> None:
    await asyncio.sleep(0)
    await am._alert_queue.join()


@pytest.mark.asyncio
async def test_truthy_return_logs_sent(caplog):
    async def notify_ok(_msg: str) -> bool:
        return True

    am = AlertManager(notify_fn=notify_ok)
    am.start()
    caplog.set_level(logging.INFO, logger="risk.alert_manager")

    await am._alert_queue.put("JARVIS TEST | OK PATH")
    await _drain(am)
    await am.stop()

    sent = [r for r in caplog.records if "[AlertManager] Sent" in r.message]
    failed = [r for r in caplog.records if "delivery failed" in r.message]
    assert len(sent) == 1 and sent[0].levelno == logging.INFO
    assert failed == []


@pytest.mark.asyncio
async def test_falsy_return_logs_delivery_failed(caplog):
    async def notify_failed(_msg: str) -> bool:
        return False

    am = AlertManager(notify_fn=notify_failed)
    am.start()
    caplog.set_level(logging.WARNING, logger="risk.alert_manager")

    await am._alert_queue.put("JARVIS TEST | FAIL PATH")
    await _drain(am)
    await am.stop()

    sent = [r for r in caplog.records if "[AlertManager] Sent" in r.message]
    failed = [r for r in caplog.records if "delivery failed" in r.message]
    assert sent == [], f"Should NOT log Sent when notify returns False, got: {sent}"
    assert len(failed) == 1 and failed[0].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_raised_exception_logs_error(caplog):
    async def notify_raises(_msg: str) -> bool:
        raise RuntimeError("boom")

    am = AlertManager(notify_fn=notify_raises)
    am.start()
    caplog.set_level(logging.ERROR, logger="risk.alert_manager")

    await am._alert_queue.put("JARVIS TEST | RAISE PATH")
    await _drain(am)
    await am.stop()

    raised = [r for r in caplog.records if "notify_fn raised" in r.message]
    sent = [r for r in caplog.records if "[AlertManager] Sent" in r.message]
    assert len(raised) == 1 and raised[0].levelno == logging.ERROR
    assert sent == []
