"""
Tests for /trades/scored-setups endpoint (proof-record.json reading).

Covers:
- file_mtime and age_seconds are populated
- 0R scratches are not counted as losses
- wrong-type rows are skipped
- goal_setups=0 falls back to DEFAULT_PROOF_GOAL
"""

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

from routers.trades_router import build_scored_setups, get_scored_setups, DEFAULT_PROOF_GOAL


def test_build_scored_setups_0r_not_counted_as_loss():
    """0R scratches should not be counted as losses."""
    raw = {
        "setups": [
            {"date": "2026-01-01", "setup": "A", "side": "LONG", "R": 1.0, "counted": True},
            {"date": "2026-01-02", "setup": "B", "side": "SHORT", "R": 0.0, "counted": True},
            {"date": "2026-01-03", "setup": "C", "side": "LONG", "R": -0.5, "counted": True},
        ],
        "goal_setups": 20,
    }
    result = build_scored_setups(raw, "test.json")
    
    assert result.counted == 3
    assert result.wins == 1
    assert result.losses == 1
    assert result.avg_r == 0.17


def test_build_scored_setups_with_file_mtime_and_age():
    """file_mtime and age_seconds are passed through."""
    raw = {"setups": [], "goal_setups": 20}
    file_mtime = "2026-10-29T21:00:00+00:00"
    age_seconds = 3600.0
    
    result = build_scored_setups(raw, "test.json", file_mtime, age_seconds)
    
    assert result.file_mtime == file_mtime
    assert result.age_seconds == age_seconds


def test_build_scored_setups_skips_wrong_type_rows():
    """Non-dict rows are skipped without crashing."""
    raw = {
        "setups": [
            {"date": "2026-01-01", "setup": "A", "side": "LONG", "R": 1.0, "counted": True},
            "this is not a dict",
            None,
            {"date": "2026-01-02", "setup": "B", "side": "SHORT", "R": -0.5, "counted": True},
        ],
        "goal_setups": 20,
    }
    result = build_scored_setups(raw, "test.json")
    
    assert result.counted == 2
    assert len(result.setups) == 2
    assert result.wins == 1
    assert result.losses == 1


def test_build_scored_setups_goal_zero_falls_back_to_default():
    """goal_setups=0 should fall back to DEFAULT_PROOF_GOAL."""
    raw = {"setups": [], "goal_setups": 0}
    result = build_scored_setups(raw, "test.json")
    
    assert result.goal_setups == DEFAULT_PROOF_GOAL


def test_build_scored_setups_goal_negative_falls_back_to_default():
    """Negative goal_setups should fall back to DEFAULT_PROOF_GOAL."""
    raw = {"setups": [], "goal_setups": -5}
    result = build_scored_setups(raw, "test.json")
    
    assert result.goal_setups == DEFAULT_PROOF_GOAL


def test_build_scored_setups_goal_string_falls_back_to_default():
    """Non-numeric goal_setups should fall back to DEFAULT_PROOF_GOAL."""
    raw = {"setups": [], "goal_setups": "twenty"}
    result = build_scored_setups(raw, "test.json")
    
    assert result.goal_setups == DEFAULT_PROOF_GOAL


def test_get_scored_setups_populates_age_seconds(monkeypatch, tmp_path):
    """get_scored_setups should populate file_mtime and age_seconds."""
    proof_file = tmp_path / "proof-record.json"
    proof_file.write_text(json.dumps({
        "setups": [
            {"date": "2026-01-01", "setup": "A", "side": "LONG", "R": 1.0, "counted": True},
        ],
        "goal_setups": 20,
    }))
    
    monkeypatch.setattr("routers.trades_router._proof_record_path", lambda: str(proof_file))
    
    result = get_scored_setups()
    
    assert result.available is True
    assert result.file_mtime is not None
    assert result.age_seconds is not None
    assert result.age_seconds >= 0
    assert result.age_seconds < 10
