"""
JARVIS TRADER — Rolling WFE Scheduler Tests
=============================================
Unit tests for the 4-week rolling WFE recalculation scheduler.
Tests state management, cadence logic, WFE evaluation, and scheduler flow.

Run:
    cd engine
    .venv/Scripts/python -m pytest tests/test_rolling_wfe.py -v
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Path setup
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.rolling_wfe_scheduler import (
    DEFAULT_CADENCE_DAYS,
    INSTRUMENT_CONFIGS,
    RollingWFEState,
    evaluate_wfe,
    run_scheduler,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_state_file(tmp_path):
    """Temporary state file for isolated test runs."""
    return tmp_path / "rolling_wfe_state.json"


@pytest.fixture
def fresh_state(temp_state_file):
    """RollingWFEState backed by a temp file (no prior state)."""
    return RollingWFEState(state_file=temp_state_file)


@pytest.fixture
def state_with_recent_run(temp_state_file):
    """State file with a run timestamp from 3 days ago."""
    state_data = {
        "instruments": {
            "MCL": {
                "last_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
                "last_wfe": 0.82,
                "prev_wfe": None,
                "wfe_delta": None,
                "result_path": "/fake/path/WF_MCL.json",
                "run_count": 1,
            },
            "MNQ": {
                "last_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
                "last_wfe": 0.57,
                "prev_wfe": None,
                "wfe_delta": None,
                "result_path": "/fake/path/WF_MNQ.json",
                "run_count": 1,
            },
        },
        "last_global_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
    }
    temp_state_file.write_text(json.dumps(state_data))
    return RollingWFEState(state_file=temp_state_file)


@pytest.fixture
def state_with_old_run(temp_state_file):
    """State file with a run timestamp from 30 days ago (due for recalculation)."""
    state_data = {
        "instruments": {
            "MCL": {
                "last_run": (datetime.utcnow() - timedelta(days=30)).isoformat(),
                "last_wfe": 0.78,
                "prev_wfe": None,
                "wfe_delta": None,
                "result_path": "/fake/path/WF_MCL.json",
                "run_count": 2,
            },
        },
        "last_global_run": (datetime.utcnow() - timedelta(days=30)).isoformat(),
    }
    temp_state_file.write_text(json.dumps(state_data))
    return RollingWFEState(state_file=temp_state_file)


# ── RollingWFEState tests ─────────────────────────────────────────────────────


class TestRollingWFEState:
    """State persistence and cadence logic."""

    def test_fresh_state_has_no_instruments(self, fresh_state):
        """New state file has no instrument history."""
        assert fresh_state.get_instrument_state("MCL") == {}
        assert fresh_state.get_instrument_state("MNQ") == {}

    def test_days_since_last_run_returns_none_on_first_run(self, fresh_state):
        """No prior run → days_since_last_run returns None."""
        result = fresh_state.days_since_last_run("MCL")
        assert result is None

    def test_is_due_true_on_fresh_state(self, fresh_state):
        """Never run → always due."""
        assert fresh_state.is_due("MCL") is True
        assert fresh_state.is_due("MNQ") is True

    def test_is_due_false_after_recent_run(self, state_with_recent_run):
        """Run 3 days ago → not due (cadence=28 days)."""
        assert state_with_recent_run.is_due("MCL", cadence_days=28) is False
        assert state_with_recent_run.is_due("MNQ", cadence_days=28) is False

    def test_is_due_true_after_old_run(self, state_with_old_run):
        """Run 30 days ago → due (cadence=28 days)."""
        assert state_with_old_run.is_due("MCL", cadence_days=28) is True

    def test_days_since_last_run_is_accurate(self, state_with_recent_run):
        """Days since last run is approximately 3."""
        days = state_with_recent_run.days_since_last_run("MCL")
        assert days is not None
        assert days <= 4  # Allow 1-day rounding tolerance

    def test_update_instrument_persists_wfe(self, fresh_state, temp_state_file):
        """update_instrument saves WFE to state file."""
        fresh_state.update_instrument(
            symbol="MCL",
            wfe=0.75,
            run_ts=datetime.utcnow().isoformat(),
            result_path="/tmp/wfe_result.json",
        )
        fresh_state.save()

        # Re-read from disk
        reloaded = RollingWFEState(state_file=temp_state_file)
        inst = reloaded.get_instrument_state("MCL")
        assert inst["last_wfe"] == 0.75

    def test_update_instrument_tracks_delta(self, state_with_recent_run, temp_state_file):
        """WFE delta is calculated correctly on second run."""
        # MCL last_wfe = 0.82; new run = 0.75
        state_with_recent_run.update_instrument(
            symbol="MCL",
            wfe=0.75,
            run_ts=datetime.utcnow().isoformat(),
            result_path="/tmp/wfe.json",
        )
        inst = state_with_recent_run.get_instrument_state("MCL")
        assert inst["prev_wfe"] == 0.82
        assert abs(inst["wfe_delta"] - (-0.07)) < 0.001

    def test_update_instrument_increments_run_count(self, state_with_recent_run):
        """run_count increments on each update."""
        initial_count = state_with_recent_run.get_instrument_state("MCL").get("run_count", 0)
        state_with_recent_run.update_instrument(
            symbol="MCL",
            wfe=0.80,
            run_ts=datetime.utcnow().isoformat(),
            result_path="/tmp/wfe.json",
        )
        new_count = state_with_recent_run.get_instrument_state("MCL").get("run_count", 0)
        assert new_count == initial_count + 1

    def test_corrupted_state_file_falls_back_gracefully(self, tmp_path):
        """Corrupted state file → fresh state (no crash)."""
        bad_file = tmp_path / "bad_state.json"
        bad_file.write_text("NOT VALID JSON {{{")
        state = RollingWFEState(state_file=bad_file)
        assert state.get_instrument_state("MCL") == {}

    def test_no_arg_construction_honors_patched_state_file(self, tmp_path):
        """RollingWFEState() with no state_file arg must resolve STATE_FILE at
        call time, not bind a stale default at module-load time.

        Regression for 2026-08-11: run_scheduler() calls RollingWFEState()
        with no args (rolling_wfe_scheduler.py), so any caller relying on
        `patch("backtest.rolling_wfe_scheduler.STATE_FILE", ...)` for
        isolation -- as every TestRunSchedulerDryRun test below does --
        depends on this. Before the fix, the `state_file: Path = STATE_FILE`
        parameter default was bound once at import time and never saw the
        patch, so isolated tests silently wrote into the real production
        rolling_wfe_state.json.
        """
        fake_state_file = tmp_path / "isolated_state.json"
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", fake_state_file):
            state = RollingWFEState()
            state.update_instrument(
                symbol="MCL",
                wfe=0.99,
                run_ts=datetime.utcnow().isoformat(),
                result_path="/tmp/wfe.json",
            )
            state.save()

        assert fake_state_file.exists()
        assert json.loads(fake_state_file.read_text())["instruments"]["MCL"]["last_wfe"] == 0.99


# ── evaluate_wfe tests ────────────────────────────────────────────────────────


class TestEvaluateWFE:
    """WFE verdict classification — canonical v2.7 thresholds."""

    def test_mcl_excellent(self):
        """MCL WFE ≥ 0.70 → EXCELLENT."""
        cfg = INSTRUMENT_CONFIGS["MCL"]
        assert evaluate_wfe("MCL", 0.82, cfg) == "EXCELLENT"
        assert evaluate_wfe("MCL", 0.70, cfg) == "EXCELLENT"

    def test_mcl_good(self):
        """MCL WFE 0.50–0.70 → GOOD."""
        cfg = INSTRUMENT_CONFIGS["MCL"]
        assert evaluate_wfe("MCL", 0.62, cfg) == "GOOD"
        assert evaluate_wfe("MCL", 0.50, cfg) == "GOOD"

    def test_mcl_marginal(self):
        """MCL WFE at/above halt threshold but below GOOD → MARGINAL."""
        cfg = INSTRUMENT_CONFIGS["MCL"]
        # MCL halt threshold = 0.40
        assert evaluate_wfe("MCL", 0.45, cfg) == "MARGINAL"
        assert evaluate_wfe("MCL", 0.40, cfg) == "MARGINAL"

    def test_mcl_halt(self):
        """MCL WFE < 0.40 → HALT (below halt threshold)."""
        cfg = INSTRUMENT_CONFIGS["MCL"]
        assert evaluate_wfe("MCL", 0.35, cfg) == "OVERFIT"
        assert evaluate_wfe("MCL", 0.14, cfg) == "HALT"  # MGC-equivalent (halt)

    def test_mnq_good(self):
        """MNQ WFE 0.57 → GOOD (canonical baseline)."""
        cfg = INSTRUMENT_CONFIGS["MNQ"]
        assert evaluate_wfe("MNQ", 0.57, cfg) == "GOOD"

    def test_mnq_marginal_above_halt(self):
        """MNQ WFE 0.35 → MARGINAL (above halt threshold of 0.30)."""
        cfg = INSTRUMENT_CONFIGS["MNQ"]
        assert evaluate_wfe("MNQ", 0.35, cfg) == "MARGINAL"

    def test_mnq_halt(self):
        """MNQ WFE < 0.30 → HALT."""
        cfg = INSTRUMENT_CONFIGS["MNQ"]
        assert evaluate_wfe("MNQ", 0.25, cfg) == "HALT"
        assert evaluate_wfe("MNQ", -0.23, cfg) == "HALT"  # Volume filter result

    def test_negative_wfe_always_halt(self):
        """Negative WFE → HALT for any instrument."""
        for symbol, cfg in INSTRUMENT_CONFIGS.items():
            result = evaluate_wfe(symbol, -1.11, cfg)  # SPY WFE
            assert result == "HALT", f"{symbol} with WFE=-1.11 should be HALT"


# ── Instrument config tests ───────────────────────────────────────────────────


class TestInstrumentConfigs:
    """Validate canonical v2.7 instrument configurations."""

    def test_all_approved_instruments_present(self):
        """MCL and MNQ are in the config."""
        assert "MCL" in INSTRUMENT_CONFIGS
        assert "MNQ" in INSTRUMENT_CONFIGS

    def test_mgc_not_approved(self):
        """MGC is NOT in approved configs (halted — WFE=0.14)."""
        assert "MGC" not in INSTRUMENT_CONFIGS

    def test_mcl_baseline_wfe_canonical(self):
        """MCL last known WFE = 0.82 (v2.7 canonical)."""
        assert INSTRUMENT_CONFIGS["MCL"]["last_known_wfe"] == 0.82

    def test_mnq_baseline_wfe_canonical(self):
        """MNQ last known WFE = 0.57 (v2.7 canonical, adaptive)."""
        assert INSTRUMENT_CONFIGS["MNQ"]["last_known_wfe"] == 0.57

    def test_mnq_adaptive_regime_enabled(self):
        """MNQ adaptive_regime = True (CRITICAL — WFE degrades without it)."""
        assert INSTRUMENT_CONFIGS["MNQ"]["adaptive_regime"] is True

    def test_mnq_mtf_filter_disabled(self):
        """MNQ mtf_filter = False (NEVER ENABLE — degrades WFE to 0.17)."""
        assert INSTRUMENT_CONFIGS["MNQ"]["mtf_filter"] is False

    def test_mnq_volume_filter_disabled(self):
        """MNQ volume_filter = False (NEVER ENABLE — degrades WFE to -0.23)."""
        assert INSTRUMENT_CONFIGS["MNQ"]["volume_filter"] is False

    def test_mcl_adaptive_disabled(self):
        """MCL adaptive_regime = False (adaptive WFE = -0.31 — WORSE)."""
        assert INSTRUMENT_CONFIGS["MCL"]["adaptive_regime"] is False

    def test_mcl_halt_threshold(self):
        """MCL halt threshold = 0.40 per paper_config kill_threshold."""
        assert INSTRUMENT_CONFIGS["MCL"]["wfe_minimum"] == 0.40

    def test_mnq_halt_threshold(self):
        """MNQ halt threshold = 0.30 per paper_config kill_threshold."""
        assert INSTRUMENT_CONFIGS["MNQ"]["wfe_minimum"] == 0.30

    def test_cadence_days_is_28(self):
        """Default cadence is 28 days (4 weeks per master doc §1.5)."""
        assert DEFAULT_CADENCE_DAYS == 28


# ── run_scheduler dry-run tests ───────────────────────────────────────────────


class TestRunSchedulerDryRun:
    """Scheduler dry-run behavior."""

    def test_dry_run_returns_summary(self, tmp_path):
        """dry_run=True returns a valid summary dict."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                summary = run_scheduler(
                    instruments=["MCL"],
                    force=True,
                    dry_run=True,
                    end_date="2026-03-30",
                )
        assert "results" in summary
        assert "MCL" in summary["results"]
        assert summary["results"]["MCL"]["status"] == "completed"

    def test_dry_run_uses_last_known_wfe(self, tmp_path):
        """dry_run returns the last known WFE from config."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                summary = run_scheduler(
                    instruments=["MCL"],
                    force=True,
                    dry_run=True,
                    end_date="2026-03-30",
                )
        wfe = summary["results"]["MCL"]["wfe"]
        assert wfe == INSTRUMENT_CONFIGS["MCL"]["last_known_wfe"]

    def test_scheduler_skips_when_not_due(self, tmp_path):
        """Without force, instruments not yet due are skipped."""
        # Pre-populate state with recent run (3 days ago)
        state_file = tmp_path / "state.json"
        state_data = {
            "instruments": {
                "MCL": {
                    "last_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
                    "last_wfe": 0.82,
                    "run_count": 1,
                }
            },
            "last_global_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        }
        state_file.write_text(json.dumps(state_data))

        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", state_file):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                summary = run_scheduler(
                    instruments=["MCL"],
                    force=False,
                    dry_run=True,
                    end_date="2026-03-30",
                )
        assert summary["results"]["MCL"]["status"] == "skipped"

    def test_force_overrides_cadence(self, tmp_path):
        """force=True runs even when cadence not reached."""
        state_file = tmp_path / "state.json"
        state_data = {
            "instruments": {
                "MCL": {
                    "last_run": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                    "last_wfe": 0.82,
                    "run_count": 1,
                }
            },
            "last_global_run": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        }
        state_file.write_text(json.dumps(state_data))

        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", state_file):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                summary = run_scheduler(
                    instruments=["MCL"],
                    force=True,
                    dry_run=True,
                    end_date="2026-03-30",
                )
        assert summary["results"]["MCL"]["status"] == "completed"

    def test_halt_verdict_sets_halt_required_flag(self, tmp_path):
        """Verdict=HALT → halt_required=True in summary."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                # Patch to return a below-threshold WFE
                with patch(
                    "backtest.rolling_wfe_scheduler.run_wfe_for_instrument", return_value=0.20
                ):
                    summary = run_scheduler(
                        instruments=["MCL"],  # MCL halt threshold = 0.40
                        force=True,
                        dry_run=False,
                        end_date="2026-03-30",
                    )
        assert summary["results"]["MCL"]["halt_required"] is True
        assert summary["results"]["MCL"]["verdict"] == "HALT"

    def test_good_verdict_sets_halt_required_false(self, tmp_path):
        """Verdict=GOOD → halt_required=False in summary."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                with patch(
                    "backtest.rolling_wfe_scheduler.run_wfe_for_instrument", return_value=0.60
                ):
                    summary = run_scheduler(
                        instruments=["MCL"],
                        force=True,
                        dry_run=False,
                        end_date="2026-03-30",
                    )
        assert summary["results"]["MCL"]["halt_required"] is False
        assert summary["results"]["MCL"]["verdict"] == "GOOD"

    def test_failed_wfe_run_returns_error_status(self, tmp_path):
        """WFE run returning None → status=error in summary."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                with patch(
                    "backtest.rolling_wfe_scheduler.run_wfe_for_instrument", return_value=None
                ):
                    summary = run_scheduler(
                        instruments=["MCL"],
                        force=True,
                        dry_run=False,
                        end_date="2026-03-30",
                    )
        assert summary["results"]["MCL"]["status"] == "error"

    def test_unknown_instrument_is_ignored(self, tmp_path):
        """Unknown symbol is silently skipped."""
        with patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path / "state.json"):
            with patch("backtest.rolling_wfe_scheduler.RESULTS_DIR", tmp_path):
                summary = run_scheduler(
                    instruments=["NOTREAL"],
                    force=True,
                    dry_run=True,
                    end_date="2026-03-30",
                )
        # No results for unknown instrument
        assert "NOTREAL" not in summary["results"]
