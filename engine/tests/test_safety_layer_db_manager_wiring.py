"""Regression: SafetyLayer must receive both db_path AND db_manager (Phase 8 Task Q4).

The `pnl_snapshots` table was empty for weeks because main.py:421 constructed
SafetyLayer with only `db_path=...` — the `db_manager` keyword was never passed.
SafetyLayer uses two DB access paths:
  - `_db_path` via raw sqlite3 → kill-switch state persistence (works)
  - `_db_manager` via typed mixin → upsert_pnl_snapshot (silently disabled)

This test locks the wiring in main.py so a future refactor can't regress it.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.safety_layer import SafetyLayer  # noqa: E402


class _FakeConfig:
    """Minimal config shim matching the fields SafetyLayer touches on init."""

    INITIAL_CAPITAL = 10000.0
    MAX_DAILY_LOSS_PCT = 0.02
    MAX_DRAWDOWN_PCT = 0.20
    KILL_SWITCH_ENABLED = True
    LIVE_TRADING_ENABLED = False
    PAPER_TRADING = True
    MAX_POSITIONS = 2
    MAX_POSITION_SIZE_PCT = 0.50


@pytest.fixture
def fake_db_manager(tmp_path: Path):
    """A MagicMock DatabaseManager that records upsert_pnl_snapshot calls."""
    m = MagicMock()
    m._db_path = tmp_path / "test.db"
    m.get_pnl_snapshot.return_value = None
    return m


# ── Core regression: wiring both args enables pnl_snapshots writes ───────────


def test_safety_layer_with_both_args_writes_snapshots(fake_db_manager):
    """Constructed with db_path AND db_manager → upsert_pnl_snapshot() fires."""
    sl = SafetyLayer(
        _FakeConfig(),
        db_path=str(fake_db_manager._db_path),
        db_manager=fake_db_manager,
    )

    # Simulate a sync tick — triggers _persist_pnl_snapshot internally
    sl.sync_from_broker(equity=10000.0, daily_pnl=50.0)

    assert fake_db_manager.upsert_pnl_snapshot.called, (
        "upsert_pnl_snapshot should have been called when db_manager is wired"
    )
    kwargs = fake_db_manager.upsert_pnl_snapshot.call_args.kwargs
    assert kwargs["daily_pnl"] == 50.0
    assert kwargs["portfolio_equity"] == 10000.0


def test_safety_layer_without_db_manager_warns_once(fake_db_manager, caplog):
    """If only db_path is passed (the old main.py bug), the write should
    silently no-op BUT log a one-shot WARNING so the next developer notices."""
    import logging

    caplog.set_level(logging.WARNING, logger="risk.safety_layer")

    sl = SafetyLayer(
        _FakeConfig(),
        db_path=str(fake_db_manager._db_path),
        # db_manager intentionally omitted — recreates the main.py:421 bug
    )

    sl.sync_from_broker(equity=10000.0, daily_pnl=50.0)
    sl.sync_from_broker(equity=10100.0, daily_pnl=100.0)
    sl.sync_from_broker(equity=10200.0, daily_pnl=150.0)

    assert not fake_db_manager.upsert_pnl_snapshot.called, (
        "upsert should NOT be called when db_manager was omitted"
    )
    warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "pnl_snapshots writes DISABLED" in r.getMessage()
    ]
    assert len(warnings) == 1, (
        f"Expected exactly one wiring-missing warning (deduped), got {len(warnings)}"
    )


def test_safety_layer_multiple_syncs_each_upsert(fake_db_manager):
    """Every sync_from_broker() tick must produce an upsert call.

    SafetyLayer also seeds one upsert at construction time (INITIAL_CAPITAL
    seed path), so total = 1 seed + N sync ticks.
    """
    sl = SafetyLayer(
        _FakeConfig(),
        db_path=str(fake_db_manager._db_path),
        db_manager=fake_db_manager,
    )
    baseline = fake_db_manager.upsert_pnl_snapshot.call_count  # usually 1 (seed)

    for pnl in [10.0, 20.0, 30.0, -5.0, 100.0]:
        sl.sync_from_broker(equity=10000.0 + pnl, daily_pnl=pnl)

    assert fake_db_manager.upsert_pnl_snapshot.call_count == baseline + 5, (
        f"Expected {baseline + 5} upsert calls (baseline {baseline} + 5 syncs), "
        f"got {fake_db_manager.upsert_pnl_snapshot.call_count}"
    )


def test_safety_layer_upsert_exception_does_not_propagate(fake_db_manager, caplog):
    """DB write failure must be logged as warning but not raise."""
    import logging

    sl = SafetyLayer(
        _FakeConfig(),
        db_path=str(fake_db_manager._db_path),
        db_manager=fake_db_manager,
    )

    # Attach the failing side effect AFTER construction to isolate the sync-tick write
    fake_db_manager.upsert_pnl_snapshot.side_effect = RuntimeError("disk full")
    caplog.set_level(logging.WARNING, logger="risk.safety_layer")

    # Must not raise
    sl.sync_from_broker(equity=10000.0, daily_pnl=0.0)

    warnings = [r for r in caplog.records if "failed to persist P&L snapshot" in r.getMessage()]
    assert len(warnings) == 1


# ── Integration-style: main.py wiring contract ───────────────────────────────


def test_main_py_wires_both_db_path_and_db_manager():
    """Grep-level contract: main.py must pass db_manager= to SafetyLayer(...)."""
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    source = main_path.read_text(encoding="utf-8")

    # Find the SafetyLayer construction and walk paren depth to find the full
    # argument block (can't use a simple non-greedy regex because args contain
    # nested parens like `str(db_manager._db_path)`).
    start = source.find("safety_layer = SafetyLayer(")
    assert start != -1, "Could not find SafetyLayer(...) construction in main.py"
    i = source.find("(", start)
    depth = 0
    end = -1
    for j in range(i, len(source)):
        if source[j] == "(":
            depth += 1
        elif source[j] == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    assert end != -1, "Unbalanced parens in SafetyLayer(...) construction"
    args = source[i + 1 : end]
    assert "db_path=" in args, "main.py:SafetyLayer must pass db_path="
    assert "db_manager=" in args, (
        "main.py:SafetyLayer must pass db_manager=. Without it, pnl_snapshots "
        "writes silently no-op every 60s."
    )
