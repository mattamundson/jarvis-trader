"""
Tests for multi-account parallel paper testing infrastructure.

Covers:
  - Default-off behaviour (ENABLE_PARALLEL_PAPER=0)
  - Challenger config whitelist and bounds enforcement
  - Forbidden-key rejection
  - Dual-emit (two rows) when enabled
  - Single-emit (one row) when disabled
  - Account stats endpoint shape
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


def _env_with(**kwargs) -> dict:
    """Return os.environ copy with specified overrides."""
    env = dict(os.environ)
    env.update({k: str(v) for k, v in kwargs.items()})
    return env


# ── 1. test_disabled_by_default ──────────────────────────────────────────────


def test_disabled_by_default():
    """ENABLE_PARALLEL_PAPER must be absent or '0' in a fresh environment."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ENABLE_PARALLEL_PAPER", None)
        from config_challenger import get_challenger_config

        result = get_challenger_config()
    assert (
        result is None
    ), "get_challenger_config() must return None when ENABLE_PARALLEL_PAPER is not set"


# ── 2. test_challenger_config_rejects_unknown_keys ───────────────────────────


def test_challenger_config_rejects_unknown_keys(tmp_path: Path):
    """Whitelist enforcement: unknown keys must raise ValueError."""
    yaml_file = tmp_path / "config-challenger.yaml"
    yaml_file.write_text("UNKNOWN_KEY: 999\n", encoding="utf-8")

    import importlib

    with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "1"}):
        import config_challenger

        importlib.reload(config_challenger)

        with patch.object(config_challenger, "_locate_yaml", return_value=yaml_file):
            with pytest.raises(ValueError, match="unknown key"):
                config_challenger.get_challenger_config()


# ── 3. test_challenger_config_rejects_out_of_range_values ────────────────────


@pytest.mark.parametrize(
    "key,bad_value",
    [
        ("MAX_POSITION_SIZE_PCT", 0.99),  # > max (0.10)
        ("MAX_POSITION_SIZE_PCT", 0.001),  # < min (0.01)
        ("MAX_CONTRACTS_PER_INSTRUMENT", 0),  # < min (1)
        ("MAX_CONTRACTS_PER_INSTRUMENT", 99),  # > max (5)
        ("MAX_DAILY_LOSS_PCT", 0.9),  # > max (0.05)
        ("MAX_DRAWDOWN_PCT", 0.001),  # < min (0.05)
        ("CONSECUTIVE_LOSS_HALT", 2),  # < min (3)
        ("CONSECUTIVE_LOSS_HALT", 11),  # > max (10)
    ],
)
def test_challenger_config_rejects_out_of_range_values(key: str, bad_value: Any, tmp_path: Path):
    """Bounds enforcement: out-of-range values must raise ValueError."""
    yaml_file = tmp_path / "config-challenger.yaml"
    yaml_file.write_text(f"{key}: {bad_value}\n", encoding="utf-8")

    import importlib

    with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "1"}):
        import config_challenger

        importlib.reload(config_challenger)

        with patch.object(config_challenger, "_locate_yaml", return_value=yaml_file):
            with pytest.raises(ValueError, match="outside the allowed range"):
                config_challenger.get_challenger_config()


# ── 4. test_challenger_config_rejects_live_trading_override ──────────────────


def test_challenger_config_rejects_live_trading_override(tmp_path: Path):
    """LIVE_TRADING_ENABLED must be permanently forbidden in challenger config."""
    yaml_file = tmp_path / "config-challenger.yaml"
    yaml_file.write_text("LIVE_TRADING_ENABLED: True\n", encoding="utf-8")

    import importlib

    with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "1"}):
        import config_challenger

        importlib.reload(config_challenger)

        with patch.object(config_challenger, "_locate_yaml", return_value=yaml_file):
            with pytest.raises(ValueError, match="forbidden"):
                config_challenger.get_challenger_config()


# ── 5. test_dual_emit_when_enabled_writes_two_trades ─────────────────────────


def test_dual_emit_when_enabled_writes_two_trades():
    """When ENABLE_PARALLEL_PAPER=1, dual_emit_paper_trade must write 2 rows."""
    calls: list[dict] = []

    mock_db = MagicMock()

    def capture_insert(**kwargs: Any) -> int:
        calls.append(dict(kwargs))
        return len(calls)

    mock_db.insert_trade = capture_insert

    # Expose account_id in the mock's signature so the shim passes it through.
    import inspect

    original_sig = inspect.Signature(
        parameters=[
            inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY)
            for k in (
                "trade_id",
                "symbol",
                "side",
                "quantity",
                "entry_price",
                "entry_time",
                "status",
                "strategy_params",
                "notes",
                "account_id",
            )
        ]
    )
    mock_db.insert_trade.__signature__ = original_sig

    with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "1"}):
        import importlib

        import parallel_paper

        importlib.reload(parallel_paper)

        trade_id = str(uuid.uuid4())
        parallel_paper.dual_emit_paper_trade(
            db_manager=mock_db,
            trade_id=trade_id,
            symbol="MES",
            side="buy",
            quantity=1.0,
            entry_price=5200.0,
            challenger_overrides={"MAX_POSITION_SIZE_PCT": 0.03},
        )

    assert len(calls) == 2, f"Expected 2 insert calls, got {len(calls)}"

    account_ids = {c["account_id"] for c in calls}
    assert account_ids == {"A", "B"}, f"Expected account_ids A and B, got {account_ids}"

    a_row = next(c for c in calls if c["account_id"] == "A")
    b_row = next(c for c in calls if c["account_id"] == "B")
    assert a_row["trade_id"] == trade_id
    assert b_row["trade_id"] != trade_id


# ── 6. test_single_emit_when_disabled_writes_one_trade ───────────────────────


def test_single_emit_when_disabled_writes_one_trade():
    """When ENABLE_PARALLEL_PAPER=0 (default), only one row is written."""
    calls: list[dict] = []

    mock_db = MagicMock()

    def capture_insert(**kwargs: Any) -> int:
        calls.append(dict(kwargs))
        return len(calls)

    mock_db.insert_trade = capture_insert

    import inspect

    original_sig = inspect.Signature(
        parameters=[
            inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY)
            for k in (
                "trade_id",
                "symbol",
                "side",
                "quantity",
                "entry_price",
                "entry_time",
                "status",
                "strategy_params",
                "notes",
                "account_id",
            )
        ]
    )
    mock_db.insert_trade.__signature__ = original_sig

    with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "0"}):
        import importlib

        import parallel_paper

        importlib.reload(parallel_paper)

        trade_id = str(uuid.uuid4())
        result = parallel_paper.dual_emit_paper_trade(
            db_manager=mock_db,
            trade_id=trade_id,
            symbol="MES",
            side="buy",
            quantity=1.0,
            entry_price=5200.0,
        )

    assert len(calls) == 1, f"Expected 1 insert call, got {len(calls)}"
    assert calls[0]["account_id"] == "A"
    assert result == trade_id


# ── 7. test_account_stats_endpoint_returns_shape ─────────────────────────────


def test_account_stats_endpoint_returns_shape():
    """
    Account stats endpoint must return the expected shape with n_trades=0
    when no trades exist for the account.
    """
    # Build an in-memory SQLite DB with the required schema.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            pnl REAL,
            status TEXT NOT NULL DEFAULT 'open',
            strategy_params TEXT,
            notes TEXT DEFAULT '',
            account_id TEXT NOT NULL DEFAULT 'A'
        )
        """
    )
    conn.commit()

    import threading

    mock_db = MagicMock()
    mock_db._lock = threading.Lock()
    mock_db._connect = lambda: conn

    # Patch the global db_manager in portfolio_router
    import importlib

    import routers.portfolio_router as pr

    importlib.reload(pr)
    pr.db_manager = mock_db

    import asyncio

    result = asyncio.run(pr.get_paper_account_stats(account_id="A", days=30))

    assert result.account_id == "A"
    assert result.days == 30
    assert result.n_trades == 0
    assert result.win_rate is None
    assert isinstance(result.equity_curve, list)


# ── 8. test_calmar_floored_below_min_dd ───────────────────────────────────────


def _seed_account_stats_db(rows: list[tuple[str, float, str]]) -> MagicMock:
    """Build an in-memory paper_trades DB with the given (pnl, exit_time) rows.

    `rows` entries are (trade_id, pnl, exit_date_iso).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            pnl REAL,
            status TEXT NOT NULL DEFAULT 'open',
            strategy_params TEXT,
            notes TEXT DEFAULT '',
            account_id TEXT NOT NULL DEFAULT 'A'
        )
        """
    )
    for trade_id, pnl, exit_time in rows:
        conn.execute(
            """
            INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, exit_price,
                 entry_time, exit_time, pnl, status, account_id)
            VALUES (?, 'MES', 'buy', 1.0, 5000.0, 5000.0, ?, ?, ?, 'closed', 'A')
            """,
            (trade_id, exit_time, exit_time, pnl),
        )
    conn.commit()

    import threading

    mock_db = MagicMock()
    mock_db._lock = threading.Lock()
    mock_db._connect = lambda: conn
    return mock_db


def test_calmar_floored_below_min_dd():
    """
    Reproduces the 2026-07-02 root-cause bug: a razor-thin drawdown
    (max_dd magnitude below CALMAR_MIN_DD_FLOOR) combined with a healthy
    annualized return must NOT explode Calmar into the millions -- it must
    come back None so the dashboard renders "--" instead of a fabricated
    ratio like 2,014,774.72.
    """
    from datetime import date, timedelta

    d0 = date.today() - timedelta(days=10)
    rows = [
        ("t1", 1000.0, (d0).isoformat()),
        ("t2", -0.01, (d0 + timedelta(days=1)).isoformat()),  # dd = -0.00001 (0.001%)
        ("t3", 1000.0, (d0 + timedelta(days=2)).isoformat()),
    ]
    mock_db = _seed_account_stats_db(rows)

    import importlib

    import routers.portfolio_router as pr

    importlib.reload(pr)
    pr.db_manager = mock_db

    import asyncio

    result = asyncio.run(pr.get_paper_account_stats(account_id="A", days=30))

    assert result.n_trades == 3
    assert result.max_dd is not None and abs(result.max_dd) < 0.005
    assert result.calmar is None, (
        f"Calmar must be floored to None when abs(max_dd)={result.max_dd} is below "
        f"CALMAR_MIN_DD_FLOOR, got {result.calmar}"
    )


def test_calmar_computed_above_min_dd():
    """Non-regression: a real (>= floor) drawdown must still produce a Calmar value."""
    from datetime import date, timedelta

    d0 = date.today() - timedelta(days=10)
    rows = [
        ("t1", 1000.0, (d0).isoformat()),
        ("t2", -100.0, (d0 + timedelta(days=1)).isoformat()),  # dd = -0.10 (10%)
        ("t3", 50.0, (d0 + timedelta(days=2)).isoformat()),
    ]
    mock_db = _seed_account_stats_db(rows)

    import importlib

    import routers.portfolio_router as pr

    importlib.reload(pr)
    pr.db_manager = mock_db

    import asyncio

    result = asyncio.run(pr.get_paper_account_stats(account_id="A", days=30))

    assert result.n_trades == 3
    assert result.max_dd is not None and abs(result.max_dd) >= 0.005
    assert result.calmar is not None
    # This magnitude bound is the actual regression guard: the pre-fix
    # formula divided a DOLLAR annualized return by a FRACTION max_dd, which
    # this exact case (10% dd, well above CALMAR_MIN_DD_FLOOR) would have
    # fabricated into the hundreds of thousands -- "is not None" alone never
    # caught it. 1000 mirrors the frontend's own fmtCalmar() clamp ceiling.
    assert abs(result.calmar) < 1000, (
        f"Calmar={result.calmar} looks like the dollar/fraction unit-mismatch "
        f"bug (fabricated blowup), not a real ratio"
    )


def test_calmar_uses_pct_of_capital_not_raw_dollars():
    """
    Reproduces the dashboard-audit bug pattern directly (Bug D, 2026-07-11):
    a healthy annualized return combined with a real (well-above-floor) 7%
    drawdown must not fabricate a six-figure Calmar like the observed
    184,195.25. The CALMAR_MIN_DD_FLOOR guard alone does NOT catch this --
    it only fires below 0.5% drawdown -- so this needs its own case.

    Pins the corrected formula exactly: CAGR (compounded off the realized
    return over the `days` window, as a fraction of settings.INITIAL_CAPITAL)
    divided by abs(max_dd) as a fraction -- both operands in the same units,
    per metrics.calmar()'s documented contract, and no longer a per-trade
    mean_pnl * 252 extrapolation.
    """
    from datetime import date, timedelta

    from config import settings

    d0 = date.today() - timedelta(days=10)
    rows = [
        ("t1", 1000.0, d0.isoformat()),
        ("t2", -70.0, (d0 + timedelta(days=1)).isoformat()),  # dd = -0.07 (7%)
        ("t3", 1000.0, (d0 + timedelta(days=2)).isoformat()),
    ]
    mock_db = _seed_account_stats_db(rows)

    import asyncio
    import importlib

    import routers.portfolio_router as pr

    importlib.reload(pr)
    pr.db_manager = mock_db

    result = asyncio.run(pr.get_paper_account_stats(account_id="A", days=30))

    assert result.max_dd == pytest.approx(-0.07, rel=1e-6)
    assert result.calmar is not None

    cumulative_pnl = result.equity_curve[-1]["equity"]
    total_return = cumulative_pnl / settings.INITIAL_CAPITAL
    expected_ann_return_pct = (1.0 + total_return) ** (365.0 / 30) - 1.0
    expected_calmar = expected_ann_return_pct / abs(result.max_dd)

    mean_pnl = (1000.0 - 70.0 + 1000.0) / 3
    buggy_calmar = (mean_pnl * 252) / abs(result.max_dd)  # pre-fix formula

    assert result.calmar == pytest.approx(expected_calmar, rel=1e-6)
    assert abs(result.calmar - buggy_calmar) > 1000, (
        "corrected and buggy formulas should differ by orders of magnitude "
        "for this case -- if they don't, the fix isn't wired in"
    )
