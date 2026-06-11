"""Tests for engine/reports/quantstats_metrics.py."""

import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_returns(n: int = 100, seed: int = 42) -> pd.Series:
    """Return a reproducible daily returns Series with a DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-02", periods=n, freq="D")
    return pd.Series(rng.normal(0.0005, 0.012, size=n), index=idx)


def _make_pnl_snapshots_db(tmp_path, rows: list[dict]) -> str:
    """Create a SQLite DB at tmp_path with a pnl_snapshots table."""
    db_path = str(tmp_path / "test.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE pnl_snapshots "
            "(date TEXT, daily_pnl REAL, portfolio_equity REAL, "
            " peak_equity REAL, consecutive_losses INTEGER, updated_at TEXT)"
        )
        for r in rows:
            conn.execute(
                "INSERT INTO pnl_snapshots (date, daily_pnl, portfolio_equity) VALUES (?, ?, ?)",
                (r["date"], r["daily_pnl"], r.get("portfolio_equity", 10000.0)),
            )
    return db_path


def _make_paper_trades_db(tmp_path, rows: list[dict]) -> str:
    """Create a SQLite DB at tmp_path with a paper_trades table only."""
    db_path = str(tmp_path / "test_trades.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE paper_trades "
            "(id INTEGER PRIMARY KEY, trade_id TEXT, symbol TEXT, side TEXT, "
            " quantity REAL, entry_price REAL, exit_price REAL, "
            " entry_time TEXT, exit_time TEXT, pnl REAL, status TEXT, notes TEXT)"
        )
        for r in rows:
            conn.execute(
                "INSERT INTO paper_trades (symbol, side, exit_time, pnl, status) "
                "VALUES (?, ?, ?, ?, 'closed')",
                (r.get("symbol", "MES"), r.get("side", "LONG"), r["exit_time"], r["pnl"]),
            )
    return db_path


def _make_both_db(tmp_path, snap_rows: list[dict], trade_rows: list[dict]) -> str:
    """Create a DB with BOTH pnl_snapshots and paper_trades."""
    db_path = str(tmp_path / "test_both.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE pnl_snapshots "
            "(date TEXT, daily_pnl REAL, portfolio_equity REAL, "
            " peak_equity REAL, consecutive_losses INTEGER, updated_at TEXT)"
        )
        for r in snap_rows:
            conn.execute(
                "INSERT INTO pnl_snapshots (date, daily_pnl, portfolio_equity) VALUES (?, ?, ?)",
                (r["date"], r["daily_pnl"], r.get("portfolio_equity", 10000.0)),
            )
        conn.execute(
            "CREATE TABLE paper_trades "
            "(id INTEGER PRIMARY KEY, trade_id TEXT, symbol TEXT, side TEXT, "
            " quantity REAL, entry_price REAL, exit_price REAL, "
            " entry_time TEXT, exit_time TEXT, pnl REAL, status TEXT, notes TEXT)"
        )
        for r in trade_rows:
            conn.execute(
                "INSERT INTO paper_trades (symbol, side, exit_time, pnl, status) "
                "VALUES (?, ?, ?, ?, 'closed')",
                (r.get("symbol", "MES"), r.get("side", "LONG"), r["exit_time"], r["pnl"]),
            )
    return db_path


# ---------------------------------------------------------------------------
# Tests: compute_quantstats_metrics
# ---------------------------------------------------------------------------


def test_compute_quantstats_metrics_basic():
    """All required keys present and correct types for a normal returns series."""
    from reports.quantstats_metrics import compute_quantstats_metrics

    returns = _make_returns(100)
    result = compute_quantstats_metrics(returns, source="pnl_snapshots")

    required_scalar_keys = ("sortino", "sharpe", "calmar", "max_dd", "win_rate", "profit_factor")
    for key in required_scalar_keys:
        assert key in result, f"Missing key: {key}"
        assert result[key] is None or isinstance(
            result[key], float
        ), f"{key} should be float or None, got {type(result[key])}"

    assert "max_dd_duration_days" in result
    assert result["max_dd_duration_days"] is None or isinstance(result["max_dd_duration_days"], int)

    assert isinstance(result["monthly_returns"], dict)
    assert isinstance(result["rolling_sharpe_30d"], list)

    assert result["source"] == "pnl_snapshots"

    # Spot-check numeric plausibility on 100 return days
    if result["max_dd"] is not None:
        assert result["max_dd"] <= 0, "max_dd should be non-positive"
    if result["win_rate"] is not None:
        assert 0.0 <= result["win_rate"] <= 1.0, "win_rate out of [0, 1]"


def test_compute_quantstats_metrics_empty_returns_shell():
    """Empty returns series produces n_trades=0, null metrics, no exception."""
    from reports.quantstats_metrics import compute_quantstats_metrics

    empty = pd.Series(dtype=float)
    result = compute_quantstats_metrics(empty, source="paper_trades")

    assert result["n_trades"] == 0
    assert result["source"] == "paper_trades"
    assert result["sortino"] is None
    assert result["sharpe"] is None
    assert result["calmar"] is None
    assert result["max_dd"] is None
    assert result["max_dd_duration_days"] is None
    assert result["win_rate"] is None
    assert result["profit_factor"] is None
    assert result["monthly_returns"] == {}
    assert result["rolling_sharpe_30d"] == []


# ---------------------------------------------------------------------------
# Tests: _load_pnl_series
# ---------------------------------------------------------------------------


def test_load_pnl_series_prefers_pnl_snapshots(tmp_path):
    """When both tables exist, pnl_snapshots is used as source."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    from reports.quantstats_metrics import _load_pnl_series

    # Use dates within the last 60 days so the cutoff window always covers them.
    today = _dt.now(_tz.utc).date()
    base_date = today - _td(days=50)
    snap_rows = [
        {
            "date": (base_date + _td(days=i)).isoformat(),
            "daily_pnl": 10.0 * (-1 if i % 3 == 0 else 1),
            "portfolio_equity": 10000.0 + i * 5,
        }
        for i in range(30)
    ]
    trade_rows = [
        {
            "exit_time": (base_date + _td(days=i)).isoformat() + "T15:00:00",
            "pnl": 50.0,
        }
        for i in range(5)
    ]
    db_path = _make_both_db(tmp_path, snap_rows, trade_rows)

    series, source, n_trades, start, end = _load_pnl_series(db_path, None, 90)
    assert source == "pnl_snapshots", f"Expected pnl_snapshots, got {source}"
    assert n_trades > 0
    assert not series.empty


def test_load_pnl_series_falls_back_to_paper_trades(tmp_path):
    """When pnl_snapshots is absent, paper_trades is used."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    from reports.quantstats_metrics import _load_pnl_series

    today = _dt.now(_tz.utc).date()
    base_date = today - _td(days=20)
    trade_rows = [
        {
            "exit_time": (base_date + _td(days=i)).isoformat() + "T15:00:00",
            "pnl": 25.0 * (1 if i % 2 == 0 else -1),
        }
        for i in range(10)
    ]
    db_path = _make_paper_trades_db(tmp_path, trade_rows)

    series, source, n_trades, start, end = _load_pnl_series(db_path, None, 365)
    assert source == "paper_trades", f"Expected paper_trades, got {source}"
    assert n_trades == 10
    assert not series.empty


def test_load_pnl_series_empty_db_no_exception(tmp_path):
    """No data in either table returns empty Series, n_trades=0, no exception."""
    from reports.quantstats_metrics import _load_pnl_series

    # Create DB with only pnl_snapshots table but no rows
    db_path = _make_pnl_snapshots_db(tmp_path, [])

    series, source, n_trades, start, end = _load_pnl_series(db_path, None, 90)
    assert n_trades == 0
    assert series.empty or len(series) == 0


# ---------------------------------------------------------------------------
# Tests: _monthly_returns
# ---------------------------------------------------------------------------


def test_monthly_returns_buckets_correctly():
    """Two calendar months produce two YYYY-MM keys."""
    from reports.quantstats_metrics import _monthly_returns

    idx = pd.date_range("2025-01-15", "2025-02-28", freq="D")
    returns = pd.Series(0.001, index=idx)
    result = _monthly_returns(returns)

    assert "2025-01" in result, f"Missing 2025-01 in {list(result.keys())}"
    assert "2025-02" in result, f"Missing 2025-02 in {list(result.keys())}"
    # Each monthly return should be compound: (1.001)^n - 1
    for v in result.values():
        assert isinstance(v, float)
        assert v > 0


def test_monthly_returns_empty_series():
    """Empty series returns empty dict."""
    from reports.quantstats_metrics import _monthly_returns

    result = _monthly_returns(pd.Series(dtype=float))
    assert result == {}


# ---------------------------------------------------------------------------
# Tests: _rolling_sharpe_30d
# ---------------------------------------------------------------------------


def test_rolling_sharpe_30d_shape():
    """60+ days of returns produces a list of {date, value} dicts."""
    from reports.quantstats_metrics import _rolling_sharpe_30d

    returns = _make_returns(n=60)
    result = _rolling_sharpe_30d(returns)

    assert isinstance(result, list)
    assert len(result) > 0, "Expected non-empty rolling Sharpe list for 60-day series"
    for item in result:
        assert "date" in item and "value" in item
        assert isinstance(item["date"], str) and len(item["date"]) == 10
        assert isinstance(item["value"], float)


def test_rolling_sharpe_30d_short_series_returns_list():
    """Fewer than 30 observations may return an empty list (no assertion on exact count)."""
    from reports.quantstats_metrics import _rolling_sharpe_30d

    returns = _make_returns(n=10)
    result = _rolling_sharpe_30d(returns)
    assert isinstance(result, list)  # must not raise


# ── Extended suite (audit F-13, 2026-06-11) ──────────────────────────────────


class TestExtendedSuite:
    """The 22-metric extension must be additive and fully nullable."""

    EXTENDED_KEYS = (
        "ulcer_index", "ulcer_perf_index", "gain_to_pain", "common_sense_ratio",
        "tail_ratio", "skew", "kurtosis", "recovery_factor", "cpc_index",
        "r_squared", "cagr", "exposure", "consecutive_losses",
        "outlier_loss_ratio", "avg_win", "avg_loss", "volatility_ann",
        "var_95", "cvar_95", "kelly_criterion", "risk_of_ruin",
    )

    def _returns(self, n=90, seed=7):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2026-01-02", periods=n)
        return pd.Series(rng.normal(0.0005, 0.01, n), index=idx)

    def test_extended_keys_present_and_finite(self):
        from reports.quantstats_metrics import compute_quantstats_metrics

        m = compute_quantstats_metrics(self._returns(), source="pnl_snapshots")
        for k in self.EXTENDED_KEYS:
            assert k in m, f"missing extended key {k}"
            assert m[k] is not None, f"extended key {k} unexpectedly null on real data"

    def test_extended_keys_null_on_empty(self):
        import pandas as pd

        from reports.quantstats_metrics import compute_quantstats_metrics

        m = compute_quantstats_metrics(pd.Series(dtype=float), source="paper_trades")
        for k in self.EXTENDED_KEYS:
            assert k in m, f"null shell missing {k}"
            assert m[k] is None

    def test_original_shape_unchanged(self):
        """Pre-extension consumers must see the exact same keys + types."""
        from reports.quantstats_metrics import compute_quantstats_metrics

        m = compute_quantstats_metrics(self._returns(), source="pnl_snapshots")
        for k in ("sortino", "sharpe", "calmar", "max_dd", "win_rate", "profit_factor"):
            assert isinstance(m[k], float)
        assert isinstance(m["monthly_returns"], dict)
        assert isinstance(m["rolling_sharpe_30d"], list)

    def test_r_squared_high_for_linear_curve(self):
        import numpy as np
        import pandas as pd

        from reports.quantstats_metrics import compute_quantstats_metrics

        idx = pd.bdate_range("2026-01-02", periods=60)
        m = compute_quantstats_metrics(
            pd.Series(np.full(60, 0.002), index=idx), source="pnl_snapshots"
        )
        assert m["r_squared"] is not None and m["r_squared"] > 0.97

    def test_consecutive_losses_integer(self):
        from reports.quantstats_metrics import compute_quantstats_metrics

        m = compute_quantstats_metrics(self._returns(), source="pnl_snapshots")
        assert isinstance(m["consecutive_losses"], int)
