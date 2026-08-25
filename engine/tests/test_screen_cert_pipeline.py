"""Tests for the S4A screen→certify pipeline core.

Covers scripts/screen_and_certify.sh's tested pieces:
``backtest/screen_cert_pipeline.py`` (candidate selection, cert env assembly,
journal append) plus an end-to-end smoke of the env-parameterized cert runner
(``backtest/run_equity_sma_cert.py``) on a synthetic cache.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import screen_cert_pipeline as scp

ENGINE_ROOT = Path(__file__).resolve().parents[1]


def _row(fast, slow, atr, trades, p_edge, pf):
    return {
        "fast": fast,
        "slow": slow,
        "atr_trail_mult": atr,
        "vix_regime_block": None,
        "total_trades": trades,
        "profit_factor": pf,
        "mc_p_positive_edge": p_edge,
    }


def _doc(rows):
    return {"symbol": "MES", "rows": rows}


# ---------------------------------------------------------------------------
# validate_symbol
# ---------------------------------------------------------------------------


def test_validate_symbol_uppercases_and_accepts():
    assert scp.validate_symbol("mes") == "MES"
    assert scp.validate_symbol("SPY") == "SPY"


@pytest.mark.parametrize("sym", ["MGC", "MCL", "MNQ", "M2K"])
def test_validate_symbol_blocks_do_not_trade(sym):
    with pytest.raises(ValueError, match="DO_NOT_TRADE"):
        scp.validate_symbol(sym)


def test_validate_symbol_rejects_unknown():
    with pytest.raises(ValueError, match="not screenable"):
        scp.validate_symbol("NOPE")


# ---------------------------------------------------------------------------
# select_candidates
# ---------------------------------------------------------------------------


def test_select_candidates_filters_sorts_and_tops():
    rows = [
        _row(1, 2, 1.0, trades=20, p_edge=0.90, pf=2.0),
        _row(1, 2, 2.0, trades=5, p_edge=0.95, pf=9.0),  # too few trades
        _row(2, 2, 1.0, trades=12, p_edge=None, pf=1.0),  # no MC
        _row(2, 2, 2.0, trades=30, p_edge=0.85, pf=1.5),
        _row(3, 2, 1.0, trades=11, p_edge=0.70, pf=1.1),
    ]
    got = scp.select_candidates(_doc(rows), top_n=2)
    assert [r["mc_p_positive_edge"] for r in got] == [0.90, 0.85]
    assert got[0]["total_trades"] == 20


def test_select_candidates_pf_tiebreak():
    rows = [
        _row(1, 2, 1.0, trades=20, p_edge=0.90, pf=1.2),
        _row(2, 2, 1.0, trades=20, p_edge=0.90, pf=3.4),
    ]
    got = scp.select_candidates(_doc(rows), top_n=1)
    assert got[0]["profit_factor"] == 3.4


def test_select_candidates_empty_when_none_pass():
    rows = [
        _row(1, 2, 1.0, trades=20, p_edge=0.50, pf=2.0),  # below p_edge floor
        _row(2, 2, 1.0, trades=3, p_edge=0.95, pf=2.0),  # below trade floor
    ]
    assert scp.select_candidates(_doc(rows)) == []


# ---------------------------------------------------------------------------
# cert_env
# ---------------------------------------------------------------------------


def test_cert_env_equity_defaults():
    env = scp.cert_env("SPY", 10, 40, 2.0)
    assert env["CERT_SYMBOL"] == "SPY"
    assert env["CERT_FAST"] == "10"
    assert env["CERT_SLOW"] == "40"
    assert env["CERT_ATR"] == "2.0"
    assert "CERT_MULT" not in env  # equity runner defaults apply
    assert "CERT_SMOKE" not in env


def test_cert_env_futures_costs():
    env = scp.cert_env("MES", 50, 200, 2.0)
    assert env["CERT_MULT"] == "5.0"
    assert env["CERT_COMMISSION"] == "0.62"
    assert env["CERT_SLIPPAGE_TICKS"] == "2.0"


def test_cert_env_smoke_and_cache_override():
    env = scp.cert_env("MES", 50, 200, 2.0, smoke=True, cache_override="x.csv")
    assert env["CERT_SMOKE"] == "1"
    assert env["CERT_CACHE"] == "x.csv"


def test_cert_env_rejects_unsupported_strategy():
    with pytest.raises(ValueError, match="no env-parameterized cert runner"):
        scp.cert_env("SPY", 10, 40, 2.0, strategy="mrb")


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


def _verdict(symbol="SPY", verdict="PASS", win_rate=0.8):
    return {
        "symbol": symbol,
        "family": "trend",
        "rank": 0,
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "created_at": "2026-08-18T12:00:00+00:00",
        "gate_v2_metrics": {
            "p_edge": 0.8,
            "pf_ci_lower": 1.5,
            "mc_95th_dd_pct": 3.2,
            "dsr": 0.8,
            "win_rate": win_rate,
        },
    }


def test_append_journal_creates_header_and_appends(tmp_path):
    p = scp.append_journal(tmp_path, _verdict(), "SPY_sma_cert_10_40_2.0.json")
    assert p == tmp_path / "_journal.csv"
    rows = list(csv.DictReader(p.open(newline="")))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["verdict"] == "PASS"
    assert rows[0]["passed_via"] == "alt"
    assert rows[0]["source_file"] == "SPY_sma_cert_10_40_2.0.json"
    assert rows[0]["wfo"] == "STRONG"  # win_rate 0.8 >= 0.75
    assert rows[0]["p_edge"] == "0.8"

    scp.append_journal(tmp_path, _verdict("MES", "FAIL", 0.4), "MES_sma_cert_50_200_2.0.json")
    rows = list(csv.DictReader(p.open(newline="")))
    assert len(rows) == 2
    assert rows[1]["symbol"] == "MES"
    assert rows[1]["verdict"] == "FAIL"
    assert rows[1]["wfo"] == "WEAK"


def test_verdict_journal_row_wfo_thresholds():
    assert scp.verdict_journal_row(_verdict(win_rate=0.8), "x")["wfo"] == "STRONG"
    assert scp.verdict_journal_row(_verdict(win_rate=0.6), "x")["wfo"] == "MODERATE"
    assert scp.verdict_journal_row(_verdict(win_rate=0.4), "x")["wfo"] == "WEAK"
    assert scp.verdict_journal_row(_verdict(win_rate=None), "x")["wfo"] == "WEAK"


# ---------------------------------------------------------------------------
# cap_pf (non-finite JSON/journal guard)
# ---------------------------------------------------------------------------


def test_cap_pf_finite_and_none():
    assert scp.cap_pf(None) is None
    assert scp.cap_pf(0.0) == 0.0
    assert scp.cap_pf(1.234) == 1.234
    assert scp.cap_pf(9.0) == scp.PF_CAP  # capped at 5.0
    assert scp.cap_pf(-3.0) == 0.0  # clamped at 0.0


def test_cap_pf_non_finite():
    assert scp.cap_pf(float("inf")) == scp.PF_CAP
    assert scp.cap_pf(float("-inf")) == 0.0
    assert scp.cap_pf(float("nan")) == 0.0


def test_journal_row_non_finite_cells_are_empty():
    v = _verdict()
    v["gate_v2_metrics"]["pf_ci_lower"] = float("inf")
    v["gate_v2_metrics"]["p_edge"] = float("nan")
    row = scp.verdict_journal_row(v, "x.json")
    assert row["pf_ci_lower"] == ""
    assert row["p_edge"] == ""
    assert row["wfo"] != ""  # classification still derived from finite data


# ---------------------------------------------------------------------------
# end-to-end: cert runner smoke on synthetic cache
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_cert_runner_smoke_end_to_end(tmp_path):
    """run_equity_sma_cert.py on synthetic data writes verdict JSON + journal row."""
    rng = np.random.default_rng(7)
    n = 800
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, n))
    cache = tmp_path / "SPY_synthetic_1d.csv"
    pd.DataFrame(
        {
            "timestamp": dates.strftime("%Y-%m-%d"),
            "open": open_.round(2),
            "high": high.round(2),
            "low": low.round(2),
            "close": close.round(2),
        }
    ).to_csv(cache, index=False)

    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "CERT_SYMBOL": "SPY",
            "CERT_FAST": "8",
            "CERT_SLOW": "20",
            "CERT_ATR": "2.0",
            "CERT_SMOKE": "1",
            "CERT_CACHE": str(cache),
            "GATE_V2_VERDICTS_DIR": str(verdicts),
        }
    )
    r = subprocess.run(
        [sys.executable, "backtest/run_equity_sma_cert.py"],
        cwd=ENGINE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert r.returncode == 0, f"cert runner failed:\n{r.stdout}\n{r.stderr}"

    out = verdicts / "SPY_sma_cert_8_20_2.0.json"
    assert out.exists(), r.stdout
    doc = json.loads(out.read_text())
    assert doc["symbol"] == "SPY"
    assert doc["verdict"] in ("PASS", "FAIL")
    # Policy-compatible schema (gate_v2_policy.VerdictSnapshot can read it).
    assert doc["family"] == "trend"
    assert doc["rank"] == 0
    assert doc["core_verdict"] in ("PASS", "FAIL")
    assert doc["alt_verdict"] in ("PASS", "FAIL", "UNSCORED")
    assert doc["gate_v2_metrics"]["windows_with_trades"] <= 3  # smoke cap
    assert isinstance(doc["gate_v2_metrics"]["oos_pfs"], list)
    assert len(doc["gate_v2_metrics"]["oos_pfs"]) <= 3

    rows = list(csv.DictReader((verdicts / "_journal.csv").open(newline="")))
    assert rows, "journal was not appended"
    assert rows[-1]["symbol"] == "SPY"
    assert rows[-1]["verdict"] == doc["verdict"]
    assert rows[-1]["source_file"] == out.name
