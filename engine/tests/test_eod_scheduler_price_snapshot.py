"""
EOD session flatten — async market_price_fn snapshot contract.

When EODScheduler is constructed with an ASYNC market_price_fn (the real
MarketDataManager.get_current_price returns dicts via coroutine),
run_session_flatten must pre-snapshot each open symbol's price via await
and then hand a SYNC dict-lookup closure to flatten_all_positions (which
is itself sync and called from within the already-running APScheduler
event loop).

Also covers the legacy sync-callable path (direct pass-through) and the
no-fetcher path (default breakeven fallback logs ERROR on the tracker
side, not tested here).

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_eod_scheduler_price_snapshot.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.mark.asyncio
async def test_run_session_flatten_async_fn_builds_snapshot_and_calls_flatten_sync() -> None:
    """Async market_price_fn → pre-snapshotted and passed as sync closure."""
    from schedulers.eod_scheduler import EODScheduler

    mock_tracker = MagicMock()
    mock_tracker.get_open_positions = MagicMock(
        return_value=[
            {"symbol": "MES", "entry_price": 7100.0},
            {"symbol": "MCL", "entry_price": 71.0},
        ]
    )
    mock_tracker.flatten_all_positions = MagicMock(
        return_value=[
            {"symbol": "MES", "pnl": 75.0},
            {"symbol": "MCL", "pnl": 50.0},
        ]
    )

    async def fake_price_fn(symbol: str) -> dict:
        table = {"MES": 7115.0, "MCL": 71.5}
        return {"price": table[symbol]}

    scheduler = EODScheduler(
        portfolio_tracker=mock_tracker, market_price_fn=fake_price_fn
    )

    await scheduler.run_session_flatten()

    mock_tracker.flatten_all_positions.assert_called_once()
    passed_kwargs = mock_tracker.flatten_all_positions.call_args.kwargs
    fn = passed_kwargs["market_price_fn"]
    assert fn("MES") == 7115.0
    assert fn("MCL") == 71.5
    assert fn("UNKNOWN") is None  # dict.get default


@pytest.mark.asyncio
async def test_run_session_flatten_async_fn_handles_exceptions_per_symbol() -> None:
    """One symbol's fetcher raising does not poison the rest."""
    from schedulers.eod_scheduler import EODScheduler

    mock_tracker = MagicMock()
    mock_tracker.get_open_positions = MagicMock(
        return_value=[{"symbol": "MES"}, {"symbol": "BROKEN"}]
    )
    mock_tracker.flatten_all_positions = MagicMock(return_value=[])

    async def flaky_fn(symbol: str) -> dict:
        if symbol == "BROKEN":
            raise RuntimeError("feed down")
        return {"price": 7115.0}

    scheduler = EODScheduler(
        portfolio_tracker=mock_tracker, market_price_fn=flaky_fn
    )
    await scheduler.run_session_flatten()

    fn = mock_tracker.flatten_all_positions.call_args.kwargs["market_price_fn"]
    assert fn("MES") == 7115.0
    assert fn("BROKEN") is None


@pytest.mark.asyncio
async def test_run_session_flatten_sync_fn_passthrough() -> None:
    """Sync market_price_fn is forwarded directly (no snapshot)."""
    from schedulers.eod_scheduler import EODScheduler

    mock_tracker = MagicMock()
    mock_tracker.flatten_all_positions = MagicMock(return_value=[])

    sync_fn = MagicMock(return_value=7100.0)
    scheduler = EODScheduler(portfolio_tracker=mock_tracker, market_price_fn=sync_fn)
    await scheduler.run_session_flatten()

    passed_kwargs = mock_tracker.flatten_all_positions.call_args.kwargs
    assert passed_kwargs["market_price_fn"] is sync_fn


@pytest.mark.asyncio
async def test_run_session_flatten_no_fn_calls_plain_flatten() -> None:
    """No market_price_fn → tracker.flatten_all_positions called bare."""
    from schedulers.eod_scheduler import EODScheduler

    mock_tracker = MagicMock()
    mock_tracker.flatten_all_positions = MagicMock(return_value=[])

    scheduler = EODScheduler(portfolio_tracker=mock_tracker, market_price_fn=None)
    await scheduler.run_session_flatten()

    kwargs = mock_tracker.flatten_all_positions.call_args.kwargs
    assert "market_price_fn" not in kwargs


@pytest.mark.asyncio
async def test_run_session_flatten_async_fn_rejects_non_positive_price() -> None:
    """Zero / None / non-numeric → snapshot value is None."""
    from schedulers.eod_scheduler import EODScheduler

    mock_tracker = MagicMock()
    mock_tracker.get_open_positions = MagicMock(
        return_value=[
            {"symbol": "A"},
            {"symbol": "B"},
            {"symbol": "C"},
        ]
    )
    mock_tracker.flatten_all_positions = MagicMock(return_value=[])

    async def fn(symbol: str) -> dict:
        return {
            "A": {"price": 0},
            "B": {"price": None},
            "C": {"price": "junk"},
        }[symbol]

    scheduler = EODScheduler(portfolio_tracker=mock_tracker, market_price_fn=fn)
    await scheduler.run_session_flatten()

    snap = mock_tracker.flatten_all_positions.call_args.kwargs["market_price_fn"]
    assert snap("A") is None
    assert snap("B") is None
    assert snap("C") is None
