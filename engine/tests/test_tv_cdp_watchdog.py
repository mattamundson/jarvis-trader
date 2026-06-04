"""
Smoke tests for engine/scripts/tv_cdp_watchdog.py

Tests:
  1. _check_port returns False when nothing is listening
  2. poll_once with dry_run=True never calls subprocess.run (schtasks)
  3. poll_once recovers (prev_reachable=False → reachable=True) sends Discord alert
     but not when debounced
  4. _trigger_recovery with dry_run=True returns 'schtasks_skipped_dry_run' without calling subprocess
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

# Import module under test
from scripts.tv_cdp_watchdog import (
    _check_port,
    _trigger_recovery,
    poll_once,
)

# ---------------------------------------------------------------------------
# Helper — unused port finder
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Test 1 — _check_port returns False for a closed port
# ---------------------------------------------------------------------------


def test_check_port_returns_false_when_nothing_listening() -> None:
    free_port = _find_free_port()
    # Nothing bound to free_port — should return False
    result = _check_port(host="127.0.0.1", port=free_port, timeout=1.0)
    assert result is False


# ---------------------------------------------------------------------------
# Test 2 — dry_run=True never calls subprocess.run
# ---------------------------------------------------------------------------


def test_trigger_recovery_dry_run_does_not_call_subprocess() -> None:
    with patch("scripts.tv_cdp_watchdog.subprocess.run") as mock_run:
        action = _trigger_recovery(dry_run=True)
    mock_run.assert_not_called()
    assert action == "schtasks_skipped_dry_run"


# ---------------------------------------------------------------------------
# Test 3 — poll_once dry_run=True, port unreachable → does not call schtasks
# ---------------------------------------------------------------------------


def test_poll_once_dry_run_does_not_call_schtasks() -> None:
    with (
        patch("scripts.tv_cdp_watchdog._check_port", return_value=False),
        patch("scripts.tv_cdp_watchdog.subprocess.run") as mock_run,
        patch("scripts.tv_cdp_watchdog._log_csv"),
    ):
        result = poll_once(dry_run=True, no_discord=True)

    mock_run.assert_not_called()
    assert result["reachable"] is False
    assert result["action"] == "schtasks_skipped_dry_run"


# ---------------------------------------------------------------------------
# Test 4 — poll_once triggers Discord on failure→success transition
# ---------------------------------------------------------------------------


def test_poll_once_sends_discord_on_recovery() -> None:
    with (
        patch("scripts.tv_cdp_watchdog._check_port", return_value=True),
        patch("scripts.tv_cdp_watchdog._send_discord_alert") as mock_alert,
        patch("scripts.tv_cdp_watchdog._log_csv"),
    ):
        result = poll_once(
            dry_run=False,
            no_discord=False,
            prev_reachable=False,  # was down
            last_alert_ts=None,  # no debounce
            debounce_seconds=3600,
        )

    mock_alert.assert_called_once()
    alert_msg = mock_alert.call_args[0][0]
    assert "9222" in alert_msg or "recovered" in alert_msg.lower()
    assert result["reachable"] is True
    assert result["action"] == "discord_recovery_alert"


# ---------------------------------------------------------------------------
# Test 5 — poll_once respects debounce (no second Discord alert within window)
# ---------------------------------------------------------------------------


def test_poll_once_debounced_recovery_skips_discord() -> None:
    import time

    recent_ts = time.monotonic() - 10  # 10 seconds ago (within 3600s debounce)

    with (
        patch("scripts.tv_cdp_watchdog._check_port", return_value=True),
        patch("scripts.tv_cdp_watchdog._send_discord_alert") as mock_alert,
        patch("scripts.tv_cdp_watchdog._log_csv"),
    ):
        result = poll_once(
            dry_run=False,
            no_discord=False,
            prev_reachable=False,
            last_alert_ts=recent_ts,
            debounce_seconds=3600,
        )

    mock_alert.assert_not_called()
    assert result["action"] == "recovery_debounced"
