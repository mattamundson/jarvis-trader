"""Tests for the run_mcpt CLI's pure loaders and reference optimizer."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from backtest import run_mcpt


def test_load_ohlc_roundtrip(tmp_path):
    idx = pd.date_range("2025-01-01", periods=5, freq="h")
    csv = tmp_path / "X.csv"
    pd.DataFrame({"timestamp": idx, "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5}).to_csv(
        csv, index=False
    )
    df = run_mcpt._load_ohlc(csv)
    assert list(df.columns) == ["open", "high", "low", "close"]  # lowercased, index dropped
    assert len(df) == 5
    assert df.index.is_monotonic_increasing


def test_load_trade_pnls_from_sqlite(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE paper_trades (symbol TEXT, status TEXT, pnl REAL)")
    conn.executemany(
        "INSERT INTO paper_trades VALUES (?,?,?)",
        [("MES", "closed", 1.0), ("MES", "closed", -2.0), ("MES", "open", 9.0),
         ("MGC", "closed", 3.0)],
    )
    conn.commit()
    conn.close()
    mes = run_mcpt._load_trade_pnls(db, None, "MES")
    assert sorted(mes) == [-2.0, 1.0]  # closed-only, symbol-filtered, open excluded
    allsym = run_mcpt._load_trade_pnls(db, None, None)
    assert len(allsym) == 3


def test_optimize_fn_returns_pair_and_pf():
    close = 100.0 * np.exp(np.cumsum(np.full(400, 0.001)))
    df = pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999, "close": close})
    params, pf = run_mcpt._optimize_fn(df)
    assert isinstance(params, tuple) and len(params) == 2
    assert pf >= 0.0


def test_is_sample_detection():
    from pathlib import Path
    assert run_mcpt._is_sample(Path("SAMPLE_MES_x_1h.csv"))
    assert run_mcpt._is_sample(Path("sample_paper_trades_mes.db"))
    assert not run_mcpt._is_sample(Path("MES_2024_2026_1h.csv"))
