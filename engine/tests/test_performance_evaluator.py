"""D3-06: performance_evaluator's `_modulate_env_risk` was a dead control.

It was called on the de-risking branch (win_rate < 0.40) and the
edge-confirmed branch (win_rate >= 0.60) of `evaluate_daily_performance`, but
its body never wrote to .env, never wrote to the database, and returned
nothing anything downstream consumed -- it only logged
"Modulation Signal Sent: Scale Base Risk by {scaler}x" at INFO level. A
post-incident review reading that log would wrongly conclude risk had
actually been reduced.

Fix (approach A, per the D3-06 backlog item): delete `_modulate_env_risk` and
its two call sites entirely, and make the surrounding branch logs honest
about taking no automatic action. These tests confirm:
  1. The dead function is gone (no reintroduction of a fake "success" log).
  2. The de-risking and edge-confirmed branches still run to completion
     without it, and log an honest message instead of a misleading one.
  3. Nothing in the file still claims a modulation signal was "sent" or
     "applied".

This is NOT a test of real risk modulation -- no such control exists, and
implementing one is explicitly out of scope for D3-06 (blocked on D1-03's
unresolved MAX_CONTRACTS ceiling policy call).

NOTE on an unrelated, pre-existing bug found while writing this test:
`analytics/performance_evaluator.py` does `from database.db_manager import
DatabaseManager`, but the real class lives in `database.manager` --
`database.db_manager` does not exist anywhere in this repo. That import bug
means the script's own `except ImportError: sys.exit(1)` guard fires on every
real invocation today. It is out of scope for D3-06 (a separate, already
broken code path unrelated to the dead risk-modulation control), so this test
stubs a `database.db_manager` shim in `sys.modules` purely to make the module
importable for testing -- it does not fix the underlying bug.
"""

import importlib
import logging
import sys
import types
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ENGINE_ROOT / "analytics" / "performance_evaluator.py"


@pytest.fixture
def performance_evaluator():
    """Import (or reload) analytics.performance_evaluator with a working
    `database.db_manager` shim, working around the unrelated pre-existing
    import bug described in the module docstring above."""
    if str(ENGINE_ROOT) not in sys.path:
        sys.path.insert(0, str(ENGINE_ROOT))

    if "database.db_manager" not in sys.modules:
        from database.manager import DatabaseManager as _RealDatabaseManager

        shim = types.ModuleType("database.db_manager")
        shim.DatabaseManager = _RealDatabaseManager
        sys.modules["database.db_manager"] = shim

    if "analytics.performance_evaluator" in sys.modules:
        module = importlib.reload(sys.modules["analytics.performance_evaluator"])
    else:
        module = importlib.import_module("analytics.performance_evaluator")
    return module


class _FakeDB:
    """Duck-typed stand-in for DatabaseManager -- only the one method
    `evaluate_daily_performance` calls needs to exist."""

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def get_recent_summary(self, limit=5):
        return self._snapshots[:limit]


def _toxic_snapshots():
    # 5 days, 1 winner -> win_rate 0.20 (<0.40), net negative -> de-risking branch.
    return [
        {"daily_pnl": -100.0},
        {"daily_pnl": -50.0},
        {"daily_pnl": 25.0},
        {"daily_pnl": -75.0},
        {"daily_pnl": -10.0},
    ]


def _confirmed_snapshots():
    # 5 days, 4 winners -> win_rate 0.80 (>=0.60), net positive -> edge-confirmed branch.
    return [
        {"daily_pnl": 100.0},
        {"daily_pnl": 50.0},
        {"daily_pnl": -10.0},
        {"daily_pnl": 75.0},
        {"daily_pnl": 10.0},
    ]


def test_modulate_env_risk_function_removed(performance_evaluator):
    """The dead control must not exist -- no reintroduced fake-success helper."""
    assert not hasattr(performance_evaluator, "_modulate_env_risk")


def test_source_no_longer_claims_a_modulation_signal_was_sent():
    """Guard against a regression that re-adds honest-looking-but-fake logging.

    The historical function name may still appear in the D3-06 explanatory
    docstring (that's a legitimate changelog note) -- what must NOT reappear
    is a `def _modulate_env_risk` definition or a call site invoking it.
    """
    text = SOURCE_PATH.read_text(encoding="utf-8")
    assert "Modulation Signal Sent" not in text
    assert "def _modulate_env_risk" not in text
    assert "_modulate_env_risk(" not in text


def test_derisking_branch_runs_without_dead_control_and_logs_honestly(
    performance_evaluator, caplog
):
    db = _FakeDB(_toxic_snapshots())
    with caplog.at_level(logging.INFO, logger=performance_evaluator.__name__):
        performance_evaluator.evaluate_daily_performance(db)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("ALGORITHMIC ROT DETECTED" in w for w in warnings)
    # Must be honest that nothing was actually changed.
    assert any("NO automatic risk modulation is applied" in w for w in warnings)
    assert not any("Modulation Signal Sent" in w for w in warnings)


def test_edge_confirmed_branch_runs_without_dead_control_and_logs_honestly(
    performance_evaluator, caplog
):
    db = _FakeDB(_confirmed_snapshots())
    with caplog.at_level(logging.INFO, logger=performance_evaluator.__name__):
        performance_evaluator.evaluate_daily_performance(db)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("EDGE CONFIRMED" in i for i in infos)
    assert not any("Modulation Signal Sent" in i for i in infos)


def test_neutral_branch_still_holds_steady(performance_evaluator, caplog):
    # 5 days, 3 winners -> win_rate 0.60 but net negative -> falls to neutral branch
    # (fails both the <0.40-and-negative and >=0.60-and-positive conditions).
    snapshots = [
        {"daily_pnl": 100.0},
        {"daily_pnl": 50.0},
        {"daily_pnl": -200.0},
        {"daily_pnl": 5.0},
        {"daily_pnl": 1.0},
    ]
    db = _FakeDB(snapshots)
    with caplog.at_level(logging.INFO, logger=performance_evaluator.__name__):
        performance_evaluator.evaluate_daily_performance(db)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("MARKET REGIME NEUTRAL" in i for i in infos)
