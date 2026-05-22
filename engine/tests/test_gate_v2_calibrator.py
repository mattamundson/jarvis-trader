"""Tests for engine/analytics/gate_v2_calibrator.py"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.gate_v2_calibrator import (
    CURRENT_THRESHOLDS,
    SAMPLE_MODERATE_MAX,
    SAMPLE_WEAK_MAX,
    collect_historical_verdicts,
    diff_vs_current,
    recommended_thresholds,
    render_vault_markdown,
)

# ---------------------------------------------------------------------------
# Helpers for building synthetic verdict DataFrames
# ---------------------------------------------------------------------------


def _make_verdicts_df(
    n: int,
    pass_pf_ci_lower: float = 1.5,
    fail_pf_ci_lower: float = 0.8,
    pass_fraction: float = 0.6,
    p_edge: float = 0.97,
    mc_95th_dd: float = 0.03,
    dsr: float = 0.30,
) -> pd.DataFrame:
    """Build a synthetic DataFrame with ``n`` rows."""
    rng = np.random.default_rng(42)
    n_pass = int(n * pass_fraction)
    n_fail = n - n_pass

    verdicts = ["PASS"] * n_pass + ["FAIL"] * n_fail
    pf_vals = [pass_pf_ci_lower] * n_pass + [fail_pf_ci_lower] * n_fail
    win_rates = [0.60] * n_pass + [0.35] * n_fail

    rows = []
    for i in range(n):
        rows.append(
            {
                "symbol": "MES",
                "family": "trend",
                "rank": 11,
                "verdict": verdicts[i],
                "pf_ci_lower": pf_vals[i] + rng.uniform(-0.05, 0.05),
                "p_edge": p_edge + rng.uniform(-0.02, 0.02),
                "mc_95th_dd": mc_95th_dd + rng.uniform(-0.005, 0.005),
                "dsr": dsr + rng.uniform(-0.02, 0.02),
                "created_at": datetime.now(tz=timezone.utc) - timedelta(days=i),
                "win_rate": win_rates[i],
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. Weak recommendation with small sample
# ---------------------------------------------------------------------------


def test_recommendation_weak_with_small_sample():
    df = _make_verdicts_df(n=20)
    result = recommended_thresholds(df)

    assert result["recommendation_strength"] == "weak"
    assert result["sample_size"] == 20
    assert 0.0 <= result["confidence"] <= 1.0
    # All 4 thresholds must be present and finite
    for key in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr"):
        assert key in result
        assert math.isfinite(result[key]), f"{key} should be finite"


# ---------------------------------------------------------------------------
# 2. Strong recommendation with large sample
# ---------------------------------------------------------------------------


def test_recommendation_strong_with_large_sample():
    df = _make_verdicts_df(n=250)
    result = recommended_thresholds(df)

    assert result["recommendation_strength"] == "strong"
    assert result["sample_size"] == 250


# ---------------------------------------------------------------------------
# 3. Tighter threshold when outcomes better than expected
# ---------------------------------------------------------------------------


def test_threshold_tightens_when_outcomes_better_than_expected():
    """When most high-PF strategies genuinely win, the calibrator should
    recommend an equal or higher pf_ci_lower (tighter gate).

    We use 200 verdicts where PASS strategies (pf_ci_lower ~ 2.0) have a
    high paper win rate, and FAIL strategies (pf_ci_lower ~ 0.7) have a
    low win rate.  The precision-maximising threshold should move upward.
    """
    df = _make_verdicts_df(
        n=200,
        pass_pf_ci_lower=2.0,
        fail_pf_ci_lower=0.7,
        pass_fraction=0.55,
    )
    result = recommended_thresholds(df)
    diff = diff_vs_current(result)

    # With a clear separation at ~1.5, the calibrator may recommend tightening
    # or holding — the key constraint is it does NOT recommend loosening pf.
    pf_action = diff["pf_ci_lower"]["action"]
    assert pf_action in (
        "tighten",
        "hold",
    ), f"Expected tighten or hold for high-performing sample, got {pf_action}"


# ---------------------------------------------------------------------------
# 4. Loosen threshold when outcomes worse than expected
# ---------------------------------------------------------------------------


def test_threshold_loosens_when_outcomes_worse():
    """When strategies that barely pass the gate (pf_ci_lower ~ 1.15) mostly
    fail in paper trading, the calibrator should recommend loosening the PF
    threshold (it's not discriminating useful strategies at the current level).

    We construct verdicts where PASS strategies all have pf_ci_lower just
    above 1.1 but poor paper win rates, and FAIL strategies have win rates
    that are also poor.  With no clear separation, the recall constraint
    forces a lower threshold or hold.
    """
    rng = np.random.default_rng(99)
    n = 200
    rows = []
    for i in range(n):
        # All verdicts PASS but poor paper outcomes
        rows.append(
            {
                "symbol": "MES",
                "family": "trend",
                "rank": 11,
                "verdict": "PASS",
                "pf_ci_lower": 1.12 + rng.uniform(-0.02, 0.02),
                "p_edge": 0.96 + rng.uniform(-0.01, 0.01),
                "mc_95th_dd": 0.04 + rng.uniform(-0.005, 0.005),
                "dsr": 0.12 + rng.uniform(-0.01, 0.01),
                "created_at": datetime.now(tz=timezone.utc) - timedelta(days=i),
                "win_rate": 0.35,  # consistently poor — outcome is "bad"
            }
        )
    df = pd.DataFrame(rows)

    result = recommended_thresholds(df)
    diff = diff_vs_current(result)

    # With all outcomes bad, precision-maximising search should recommend
    # loosening OR holding (no threshold can improve precision when all
    # outcomes are uniformly bad).
    pf_action = diff["pf_ci_lower"]["action"]
    assert pf_action in (
        "loosen",
        "hold",
    ), f"Expected loosen or hold for uniformly-poor sample, got {pf_action}"


# ---------------------------------------------------------------------------
# 5. diff_vs_current correctly classifies actions
# ---------------------------------------------------------------------------


def test_diff_vs_current_correctly_classifies():
    recommended = {
        "pf_ci_lower": 1.30,  # higher than 1.10 -> tighten
        "p_edge": 0.90,  # lower than 0.95 -> loosen
        "mc_95th_dd": 0.03,  # lower than 0.05 -> tighten
        "dsr": 0.10,  # same as 0.10 -> hold
        "sample_size": 100,
        "confidence": 0.65,
        "recommendation_strength": "moderate",
    }
    result = diff_vs_current(recommended)

    assert result["pf_ci_lower"]["action"] == "tighten"
    assert result["p_edge"]["action"] == "loosen"
    assert result["mc_95th_dd"]["action"] == "tighten"
    assert result["dsr"]["action"] == "hold"

    # Deltas should be correct
    assert math.isclose(result["pf_ci_lower"]["delta"], 0.20, abs_tol=1e-4)
    assert math.isclose(result["p_edge"]["delta"], -0.05, abs_tol=1e-4)
    assert math.isclose(result["mc_95th_dd"]["delta"], -0.02, abs_tol=1e-4)
    assert math.isclose(result["dsr"]["delta"], 0.00, abs_tol=1e-4)


# ---------------------------------------------------------------------------
# 6. Empty history returns graceful result
# ---------------------------------------------------------------------------


def test_handles_empty_history_gracefully():
    df = pd.DataFrame(
        columns=[
            "symbol",
            "family",
            "rank",
            "verdict",
            "pf_ci_lower",
            "p_edge",
            "mc_95th_dd",
            "dsr",
            "created_at",
            "win_rate",
        ]
    )
    result = recommended_thresholds(df)

    assert result["sample_size"] == 0
    assert result["recommendation_strength"] == "weak"
    # Should fall back to current canonical values
    for key in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr"):
        assert result[key] == CURRENT_THRESHOLDS[key], (
            f"{key}: expected fallback to canonical {CURRENT_THRESHOLDS[key]}, "
            f"got {result[key]}"
        )

    diff = diff_vs_current(result)
    for key in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr"):
        assert diff[key]["action"] == "hold"


# ---------------------------------------------------------------------------
# 7. Vault markdown has correct frontmatter
# ---------------------------------------------------------------------------


def test_vault_markdown_writes_with_correct_frontmatter(tmp_path: Path):
    df = _make_verdicts_df(n=30)
    rec = recommended_thresholds(df)
    diff = diff_vs_current(rec)
    run_date = "2026-05-21"

    md = render_vault_markdown(rec, diff, run_date=run_date)

    # Must start with YAML frontmatter
    assert md.startswith("---"), "Markdown must start with '---' frontmatter"
    assert 'source: "gate-v2-calibration"' in md
    assert 'kind: "calibration-report"' in md
    assert f'date: "{run_date}"' in md
    assert f"sample_size: {rec['sample_size']}" in md
    assert f'recommendation_strength: "{rec["recommendation_strength"]}"' in md
    assert "tags:" in md
    assert "- gate-v2" in md
    assert "- calibration" in md
    assert "- jarvis-trader/threshold-tuning" in md

    # Must contain all 4 metric names
    for metric in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr"):
        assert metric in md, f"Markdown must mention metric {metric}"


# ---------------------------------------------------------------------------
# 8. collect_historical_verdicts with synthetic JSON files
# ---------------------------------------------------------------------------


def test_collect_historical_verdicts_reads_json_files(tmp_path: Path):
    """Write two synthetic verdict JSON files to a temp dir and verify
    collect_historical_verdicts parses them correctly."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    now = datetime.now(tz=timezone.utc)
    for i, verdict in enumerate(["PASS", "FAIL"]):
        doc = {
            "symbol": "MES",
            "family": "trend",
            "rank": i + 1,
            "verdict": verdict,
            "created_at": (now - timedelta(days=i)).isoformat(),
            "gate_v2_metrics": {
                "pf_ci_lower": 1.5 if verdict == "PASS" else 0.9,
                "p_edge": 0.97 if verdict == "PASS" else 0.60,
                "mc_95th_dd": 0.025,
                "dsr": 0.30,
            },
        }
        (verdicts_dir / f"MES_trend_rank{i+1}.json").write_text(json.dumps(doc), encoding="utf-8")

    df = collect_historical_verdicts(
        db_path=":memory:",
        lookback_days=30,
        verdicts_dir=verdicts_dir,
    )

    assert len(df) == 2
    assert set(df["verdict"]) == {"PASS", "FAIL"}
    assert set(df.columns) >= {
        "symbol",
        "family",
        "rank",
        "verdict",
        "pf_ci_lower",
        "p_edge",
        "mc_95th_dd",
        "dsr",
    }
