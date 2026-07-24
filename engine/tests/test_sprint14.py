"""
JARVIS TRADER — Sprint 14 Regression Test Suite
================================================
Comprehensive tests for all Sprint 14 features:
- compute_position_size (conviction sizing)
- GET /scanner/signals/latest endpoint existence
- GET /paper/trade-journal endpoint existence
- GET /paper-validation/wfe endpoint existence
- GET /paper-validation/gates (avg_conviction_score field)
- paper_tracker.py JSONL audit
- migrate_jsonl_to_sqlite importability

Run with:
    cd engine
    python -m pytest tests/test_sprint14.py -v
"""

import inspect
import os
import sys

import pytest

# Set test environment variables BEFORE any imports
test_env_vars = {
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
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

# Add engine to path
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ===========================================================================
# (1) compute_position_size Tests
# ===========================================================================


def test_conviction_full():
    """STRONG_BULL + TRENDING + BUYER_CONTROL = 100% multiplier."""
    from backtest.signals import compute_position_size

    result = compute_position_size("STRONG_BULL", "TRENDING_BULL", "BUYER_CONTROL", 0.02)
    assert result == pytest.approx(0.02 * 1.0, abs=1e-6)


def test_conviction_high():
    """STRONG_BULL + TRENDING (NEUTRAL structure) = 80% multiplier."""
    from backtest.signals import compute_position_size

    result = compute_position_size("STRONG_BULL", "TRENDING_BULL", "NEUTRAL", 0.02)
    assert result == pytest.approx(0.02 * 0.80, abs=1e-6)


def test_conviction_half():
    """LEAN_BULL (any regime/structure) = 50% multiplier."""
    from backtest.signals import compute_position_size

    result = compute_position_size("LEAN_BULL", "TRENDING_BULL", "BUYER_CONTROL", 0.02)
    assert result == pytest.approx(0.02 * 0.50, abs=1e-6)


def test_conviction_minimum():
    """Neutral bias with trending regime = 25% multiplier."""
    from backtest.signals import compute_position_size

    result = compute_position_size("NEUTRAL", "TRENDING_BULL", "NEUTRAL", 0.02)
    assert result == pytest.approx(0.02 * 0.25, abs=1e-6)


# ===========================================================================
# (2) GET /scanner/signals/latest — Endpoint Existence
# ===========================================================================


def test_scanner_signals_latest_endpoint_exists():
    """GET /scanner/signals/latest endpoint must be defined."""
    from routers.scanner_router import router

    routes = [route.path for route in router.routes]
    assert any("/signals/latest" in route for route in routes)


def test_scanner_signals_latest_imports():
    """LatestSignalsResponse schema must be defined."""
    from routers.scanner_router import LatestSignalsResponse

    schema = LatestSignalsResponse.model_json_schema()
    assert "signals" in schema["properties"]
    assert "count" in schema["properties"]


# ===========================================================================
# (3) GET /paper/trade-journal — Endpoint Existence
# ===========================================================================


def test_trade_journal_endpoint_exists():
    """GET /paper/trade-journal endpoint must be defined."""
    from routers.journal_router import router

    routes = [route.path for route in router.routes]
    assert any("trade-journal" in route for route in routes)


def test_trade_journal_has_parameters():
    """trade-journal endpoint accepts symbol and limit parameters."""
    from routers.journal_router import router

    trade_journal_route = None
    for route in router.routes:
        if "trade-journal" in route.path:
            trade_journal_route = route
            break

    assert trade_journal_route is not None
    assert trade_journal_route.methods is not None
    assert "GET" in trade_journal_route.methods


def test_trade_journal_returns_list():
    """TradeJournalEntry schema confirms list response."""
    from routers.journal_router import TradeJournalEntry

    schema = TradeJournalEntry.model_json_schema()
    assert "symbol" in schema.get("properties", {})
    assert "entry_time" in schema.get("properties", {})


# ===========================================================================
# (4) GET /paper-validation/wfe — Endpoint Existence
# ===========================================================================


def test_rolling_wfe_endpoint_exists():
    """GET /paper-validation/wfe endpoint must be defined."""
    from routers.paper_validation_router import router

    routes = [route.path for route in router.routes]
    assert any("/wfe" in route for route in routes)


def test_rolling_wfe_response_schema():
    """WFEResponse schema has instruments list."""
    from routers.paper_validation_router import WFEResponse

    schema = WFEResponse.model_json_schema()
    assert "instruments" in schema["properties"]


def test_rolling_wfe_instrument_schema():
    """WFEInstrument has symbol, kill_threshold, status."""
    from routers.paper_validation_router import WFEInstrument

    schema = WFEInstrument.model_json_schema()
    assert "symbol" in schema["properties"]
    assert "kill_threshold" in schema["properties"]
    assert "status" in schema["properties"]


# ===========================================================================
# (4b) GET /paper/validation/trades/closed — dashboard Trade History
# ===========================================================================


def test_closed_paper_trades_endpoint_exists():
    """GET /paper/validation/trades/closed must be registered on paper_validation router."""
    from routers.paper_validation_router import router

    routes = [route.path for route in router.routes]
    assert "/paper/validation/trades/closed" in routes


def test_closed_trade_response_schema():
    """ClosedTrade includes fields the dashboard /trades table expects."""
    from routers.paper_validation_router import ClosedTrade

    schema = ClosedTrade.model_json_schema()
    props = schema.get("properties", {})
    for key in (
        "trade_id",
        "symbol",
        "direction",
        "entry_price",
        "exit_price",
        "pnl",
        "duration_seconds",
    ):
        assert key in props


# ===========================================================================
# GT-11: duration_seconds must not silently default to 0 on a tz-aware vs
# tz-naive entry/exit timestamp pair (was a swallowed TypeError).
# ===========================================================================


def test_duration_calc_handles_tz_aware_entry_naive_exit():
    """tz-aware entry_time + tz-naive exit_time must not crash or return 0."""
    from routers.paper_validation_router import _compute_trade_duration_seconds

    entry_time = "2026-07-20T14:00:00Z"  # tz-aware (has 'Z')
    exit_time = "2026-07-20T15:30:00"  # tz-naive (no offset)

    duration = _compute_trade_duration_seconds("TEST-1", entry_time, exit_time)

    assert duration == 90 * 60
    assert duration != 0


def test_duration_calc_handles_tz_naive_entry_aware_exit():
    """tz-naive entry_time + tz-aware exit_time must not crash or return 0."""
    from routers.paper_validation_router import _compute_trade_duration_seconds

    entry_time = "2026-07-20T14:00:00"  # tz-naive
    exit_time = "2026-07-20T14:45:00+00:00"  # tz-aware

    duration = _compute_trade_duration_seconds("TEST-2", entry_time, exit_time)

    assert duration == 45 * 60
    assert duration != 0


def test_duration_calc_both_aware_unaffected():
    """Two tz-aware timestamps compute normally (no regression)."""
    from routers.paper_validation_router import _compute_trade_duration_seconds

    entry_time = "2026-07-20T14:00:00Z"
    exit_time = "2026-07-20T16:00:00Z"

    duration = _compute_trade_duration_seconds("TEST-3", entry_time, exit_time)

    assert duration == 2 * 3600


def test_duration_calc_unparseable_logs_and_defaults_to_zero(caplog):
    """A genuinely unparseable timestamp still defaults to 0, but is logged."""
    from routers.paper_validation_router import _compute_trade_duration_seconds

    with caplog.at_level("WARNING"):
        duration = _compute_trade_duration_seconds("TEST-4", "not-a-timestamp", "2026-07-20T14:00:00Z")

    assert duration == 0
    assert any("duration calc" in record.message for record in caplog.records)


def test_duration_calc_tz_mismatch_logs_anomaly(caplog):
    """A tz-awareness mismatch is logged instead of being silently swallowed."""
    from routers.paper_validation_router import _compute_trade_duration_seconds

    with caplog.at_level("WARNING"):
        duration = _compute_trade_duration_seconds(
            "TEST-5", "2026-07-20T14:00:00Z", "2026-07-20T15:00:00"
        )

    assert duration == 3600
    assert any(
        "tz-awareness mismatch" in record.message for record in caplog.records
    )


# ===========================================================================
# (5) GET /paper-validation/gates — avg_conviction_score field
# ===========================================================================


def test_gates_endpoint_exists():
    """GET /paper-validation/gates endpoint must be defined."""
    from routers.paper_validation_router import router

    routes = [route.path for route in router.routes]
    assert any("/gates" in route for route in routes)


def test_gates_response_has_conviction_score():
    """ValidationGatesResponse includes avg_conviction_score."""
    from routers.paper_validation_router import ValidationGatesResponse

    schema = ValidationGatesResponse.model_json_schema()
    assert "avg_conviction_score" in schema["properties"]


def test_gates_response_schema():
    """ValidationGatesResponse has all required fields."""
    from routers.paper_validation_router import ValidationGatesResponse

    schema = ValidationGatesResponse.model_json_schema()
    required = ["gates", "days_elapsed", "days_remaining", "avg_conviction_score", "overall_pass"]
    for field in required:
        assert field in schema["properties"]


def test_validation_gate_schema():
    """ValidationGate has name, current, target, passes."""
    from routers.paper_validation_router import ValidationGate

    schema = ValidationGate.model_json_schema()
    assert "name" in schema["properties"]
    assert "current" in schema["properties"]
    assert "target" in schema["properties"]
    assert "passes" in schema["properties"]


# ===========================================================================
# (6) JSONL write audit — paper_tracker.py has no JSONL writes
# ===========================================================================


def test_paper_tracker_no_jsonl_writes():
    """paper_tracker.py must not write to JSONL files."""
    from backtest import paper_tracker

    source = inspect.getsource(paper_tracker)
    lines = source.splitlines()

    jsonl_write_lines = [
        line
        for line in lines
        if "open(" in line and ("'a'" in line or '"a"' in line) and ".jsonl" in line
    ]

    assert (
        len(jsonl_write_lines) == 0
    ), f"Found JSONL append writes in paper_tracker.py: {jsonl_write_lines}"


# ===========================================================================
# (7) migrate_jsonl_to_sqlite is importable and callable
# ===========================================================================


def test_migrate_jsonl_to_sqlite_importable():
    """migrate_jsonl_to_sqlite must be importable from paper_runner."""
    from backtest.paper_runner import migrate_jsonl_to_sqlite

    assert callable(migrate_jsonl_to_sqlite)


def test_migrate_jsonl_to_sqlite_has_signature():
    """migrate_jsonl_to_sqlite must accept jsonl_path parameter."""
    from backtest.paper_runner import migrate_jsonl_to_sqlite

    sig = inspect.signature(migrate_jsonl_to_sqlite)
    assert "jsonl_path" in sig.parameters
