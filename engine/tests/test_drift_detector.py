"""
Unit tests for DriftDetector (engine/analytics/drift_detector.py).

Covers the two correctness fixes landed alongside this file:
  1. consecutive_weeks must count ISO weeks, not invocations — running the
     detector multiple times in the same calendar week counts once.
  2. _get_baseline_pf picks the verdict by its own created_at, not the file's
     (mutable) mtime.

Plus the basic contracts: PF-vs-threshold drift flag, state round-trip, and
the insufficient_data short-circuit.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from analytics import drift_detector as dd
from analytics.drift_detector import DriftDetector


class _FakeDB:
    """Minimal db_manager stub: fetch_one returns a preset row dict."""

    def __init__(self, row):
        self._row = row
        self.calls = 0

    def fetch_one(self, sql, params):
        self.calls += 1
        return self._row


@pytest.fixture
def detector(tmp_path, monkeypatch):
    """A DriftDetector whose state file lives in tmp_path (no real data/ writes)."""
    monkeypatch.setattr(DriftDetector, "_ensure_data_dir", lambda self: None)
    db = _FakeDB(row={"gross_profit": 10.0, "gross_loss": 100.0, "trade_count": 5})
    det = DriftDetector(db)
    det.drift_state_file = tmp_path / "drift_state.json"
    det.drift_state_file.write_text("{}", encoding="utf-8")
    return det


def test_state_round_trip(detector):
    payload = {"MES": {"consecutive_weeks": 2, "history": [], "last_drift_week": "2026-W23"}}
    detector._save_state(payload)
    assert detector._load_state() == payload


@pytest.mark.asyncio
async def test_pf_below_threshold_flags_drift(detector):
    # baseline default 1.2 -> threshold 0.72; live_pf = 10/100 = 0.10 < 0.72
    out = await detector.check_drift("MES")
    assert out["live_pf"] == pytest.approx(0.10, abs=1e-3)
    assert out["consecutive_fail_weeks"] == 1
    assert out["trigger_alert"] is False  # 1 week, needs 3


@pytest.mark.asyncio
async def test_same_week_is_idempotent(detector):
    """Two checks in the SAME ISO week must not double-count the streak."""
    first = await detector.check_drift("MES")
    second = await detector.check_drift("MES")
    assert first["consecutive_fail_weeks"] == 1
    assert second["consecutive_fail_weeks"] == 1  # still 1, not 2


@pytest.mark.asyncio
async def test_recovery_resets_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(DriftDetector, "_ensure_data_dir", lambda self: None)
    # Pre-seed a drifting streak from a prior week, then feed a healthy PF.
    db = _FakeDB(row={"gross_profit": 200.0, "gross_loss": 100.0, "trade_count": 5})
    det = DriftDetector(db)
    det.drift_state_file = tmp_path / "drift_state.json"
    det.drift_state_file.write_text(
        json.dumps({"MES": {"consecutive_weeks": 2, "history": [], "last_drift_week": "2026-W01"}}),
        encoding="utf-8",
    )
    out = await det.check_drift("MES")  # live_pf = 2.0, well above threshold
    assert out["consecutive_fail_weeks"] == 0
    assert det._load_state()["MES"]["last_drift_week"] is None


@pytest.mark.asyncio
async def test_insufficient_data_short_circuits(tmp_path, monkeypatch):
    monkeypatch.setattr(DriftDetector, "_ensure_data_dir", lambda self: None)
    db = _FakeDB(row={"gross_profit": 0.0, "gross_loss": 0.0, "trade_count": 1})
    det = DriftDetector(db)
    det.drift_state_file = tmp_path / "drift_state.json"
    det.drift_state_file.write_text("{}", encoding="utf-8")
    out = await det.check_drift("MES")
    assert out["status"] == "insufficient_data"


def test_baseline_picked_by_created_at_not_mtime(detector, tmp_path, monkeypatch):
    """Newer created_at must win even when its file has an OLDER mtime."""
    vdir = tmp_path / "verdicts"
    vdir.mkdir()

    newer = vdir / "MES_strat_rank1.json"
    older = vdir / "MES_strat_rank2.json"
    newer.write_text(
        json.dumps(
            {"created_at": "2026-05-31T00:00:00+00:00", "gate_v2_metrics": {"fixed_params_min_pf": 1.9}}
        ),
        encoding="utf-8",
    )
    older.write_text(
        json.dumps(
            {"created_at": "2026-01-01T00:00:00+00:00", "gate_v2_metrics": {"fixed_params_min_pf": 1.1}}
        ),
        encoding="utf-8",
    )
    # Invert mtime ordering: give the NEWER-content file an OLDER mtime.
    old_ts = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    new_ts = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
    os.utime(newer, (old_ts, old_ts))
    os.utime(older, (new_ts, new_ts))

    monkeypatch.setattr(dd, "VERDICTS_DIR", vdir)
    assert detector._get_baseline_pf("MES") == pytest.approx(1.9)


def test_baseline_default_when_no_verdicts(detector, tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "VERDICTS_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert detector._get_baseline_pf("ZZZ") == pytest.approx(1.2)
