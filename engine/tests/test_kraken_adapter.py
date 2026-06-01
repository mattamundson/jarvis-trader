"""
Unit tests for KrakenAdapter. All subprocess invocations are mocked — these
tests DO NOT require the kraken-cli binary or network access.

Every test locks in one behavior so regressions point at a specific failure
mode. Paper vs live selection and rate-limit backoff are the two most
likely to drift, so they get dedicated cases.
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_unavailable_when_binary_not_on_path():
    """is_available returns False when `kraken` is not on PATH."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    with patch("markets.crypto.kraken_adapter.shutil.which", return_value=None):
        adapter = KrakenAdapter()
        assert adapter.is_available() is False


def test_available_when_binary_found():
    """is_available returns True when `kraken` is on PATH."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    with patch(
        "markets.crypto.kraken_adapter.shutil.which",
        return_value="/fake/path/kraken",
    ):
        adapter = KrakenAdapter()
        assert adapter.is_available() is True


def test_is_available_caches_result():
    """Repeated calls to is_available don't re-invoke shutil.which."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    with patch(
        "markets.crypto.kraken_adapter.shutil.which",
        return_value="/fake/path/kraken",
    ) as mock_which:
        adapter = KrakenAdapter()
        adapter.is_available()
        adapter.is_available()
        adapter.is_available()
        assert mock_which.call_count == 1


# ---------------------------------------------------------------------------
# paper_mode property
# ---------------------------------------------------------------------------


def test_paper_mode_default():
    from markets.crypto.kraken_adapter import KrakenAdapter

    adapter = KrakenAdapter()
    assert adapter.paper_mode is True


def test_paper_mode_when_live_enabled():
    from markets.crypto.kraken_adapter import KrakenAdapter

    adapter = KrakenAdapter(live_enabled=True)
    assert adapter.paper_mode is False


# ---------------------------------------------------------------------------
# _run helper — subprocess orchestration
# ---------------------------------------------------------------------------


def _make_mock_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Factory: returns a mock async subprocess object."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.asyncio
async def test_run_parses_json_stdout():
    """_run returns parsed JSON on rc=0 with valid JSON stdout."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    mock_proc = _make_mock_proc(stdout=b'{"balance": 10000.0}')
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ),
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance", "-o", "json"])
        assert result == {"balance": 10000.0}


@pytest.mark.asyncio
async def test_run_returns_none_on_nonzero_exit():
    """_run returns None when the CLI exits nonzero."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    mock_proc = _make_mock_proc(stderr=b"auth failed", returncode=2)
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ),
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance"])
        assert result is None


@pytest.mark.asyncio
async def test_run_returns_none_on_invalid_json():
    """_run returns None when stdout is not valid JSON."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    mock_proc = _make_mock_proc(stdout=b"not json at all")
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ),
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance"])
        assert result is None


@pytest.mark.asyncio
async def test_run_returns_none_when_binary_missing():
    """_run returns None without invoking subprocess when binary is missing."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value=None),
        patch("markets.crypto.kraken_adapter.asyncio.create_subprocess_exec") as mock_exec,
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance"])
        assert result is None
        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_rate_limit_backoff_exhausts_retries():
    """Persistent 429 → _run retries up to _MAX_RETRIES then gives up."""
    from markets.crypto.kraken_adapter import _MAX_RETRIES, KrakenAdapter

    mock_proc = _make_mock_proc(stderr=b"429 Too Many Requests", returncode=1)
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec,
        patch("markets.crypto.kraken_adapter.asyncio.sleep", new=AsyncMock()),
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance"])
        assert result is None
        assert mock_exec.call_count == _MAX_RETRIES


@pytest.mark.asyncio
async def test_rate_limit_backoff_recovers():
    """429 on first attempt, success on retry → _run returns parsed JSON."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    first = _make_mock_proc(stderr=b"429 rate limit", returncode=1)
    second = _make_mock_proc(stdout=b'{"ok": true}')
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            side_effect=[first, second],
        ),
        patch("markets.crypto.kraken_adapter.asyncio.sleep", new=AsyncMock()),
    ):
        adapter = KrakenAdapter()
        result = await adapter._run(["balance"])
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Paper vs live selection in submit_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_order_paper_mode_prefixes_paper():
    """In paper mode, submit_order invokes `kraken paper buy ...`."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    captured_args = {}

    async def capture_exec(*cmd, **kwargs):
        captured_args["cmd"] = list(cmd)
        return _make_mock_proc(stdout=b'{"order_id": "P-1"}')

    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            side_effect=capture_exec,
        ),
    ):
        adapter = KrakenAdapter(live_enabled=False)
        result = await adapter.submit_order(
            symbol="BTCUSD", side="buy", quantity=0.01, limit_price=50000
        )
        assert result == {"order_id": "P-1"}
        cmd = captured_args["cmd"]
        # Command must look like: ['/fake/kraken', 'paper', 'buy', 'BTCUSD', '0.01', ...]
        assert cmd[1] == "paper"
        assert cmd[2] == "buy"
        assert "BTCUSD" in cmd
        assert "0.01" in cmd
        assert "--price" in cmd
        assert "50000" in cmd


@pytest.mark.asyncio
async def test_submit_order_live_mode_omits_paper_prefix():
    """In live mode, submit_order invokes `kraken order buy ...`."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    captured_args = {}

    async def capture_exec(*cmd, **kwargs):
        captured_args["cmd"] = list(cmd)
        return _make_mock_proc(stdout=b'{"order_id": "L-1"}')

    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            side_effect=capture_exec,
        ),
    ):
        adapter = KrakenAdapter(live_enabled=True)
        await adapter.submit_order(symbol="BTCUSD", side="sell", quantity=0.02)
        cmd = captured_args["cmd"]
        assert cmd[1] == "order"
        assert cmd[2] == "sell"
        assert "paper" not in cmd


@pytest.mark.asyncio
async def test_submit_order_rejects_invalid_side():
    """Invalid side returns None without invoking subprocess."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch("markets.crypto.kraken_adapter.asyncio.create_subprocess_exec") as mock_exec,
    ):
        adapter = KrakenAdapter()
        result = await adapter.submit_order(symbol="BTCUSD", side="long", quantity=0.01)
        assert result is None
        mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# get_positions / get_balance / get_daily_pnl shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_positions_flat_list():
    """get_positions flattens a top-level list response (live mode)."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    payload = b'[{"symbol":"BTCUSD","quantity":0.1}]'
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=_make_mock_proc(stdout=payload),
        ),
    ):
        adapter = KrakenAdapter(live_enabled=True)
        positions = await adapter.get_positions()
        assert positions == [{"symbol": "BTCUSD", "quantity": 0.1}]


@pytest.mark.asyncio
async def test_get_positions_nested_positions_key():
    """get_positions unwraps {"positions": [...]} shape (live mode)."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    payload = b'{"positions": [{"symbol":"ETHUSD","quantity":1.0}]}'
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=_make_mock_proc(stdout=payload),
        ),
    ):
        adapter = KrakenAdapter(live_enabled=True)
        positions = await adapter.get_positions()
        assert positions == [{"symbol": "ETHUSD", "quantity": 1.0}]


@pytest.mark.asyncio
async def test_get_daily_pnl_extracts_primary_key():
    """get_daily_pnl reads the first known pnl key from the response dict (live mode)."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    payload = b'{"daily_pnl": 42.5, "pnl_today": 0.0}'
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=_make_mock_proc(stdout=payload),
        ),
    ):
        adapter = KrakenAdapter(live_enabled=True)
        pnl = await adapter.get_daily_pnl()
        assert pnl == 42.5


@pytest.mark.asyncio
async def test_get_daily_pnl_fallback_zero():
    """get_daily_pnl returns 0.0 when no recognizable pnl key is present."""
    from markets.crypto.kraken_adapter import KrakenAdapter

    payload = b'{"unrecognized": 99}'
    with (
        patch("markets.crypto.kraken_adapter.shutil.which", return_value="/fake/kraken"),
        patch(
            "markets.crypto.kraken_adapter.asyncio.create_subprocess_exec",
            return_value=_make_mock_proc(stdout=payload),
        ),
    ):
        adapter = KrakenAdapter()
        pnl = await adapter.get_daily_pnl()
        assert pnl == 0.0
