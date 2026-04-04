"""Tests for n-autoresearch experiment loop."""

import json
import os

import pytest

from strategies.experiment_log import ExperimentLog
from strategies.search_strategy import select_next_config


def test_experiment_log_instantiation(tmp_path):
    log = ExperimentLog(str(tmp_path / "test_log.json"))
    assert log.all() == []
    assert log.best_by_wfe() is None


def test_experiment_log_roundtrip(tmp_path):
    path = str(tmp_path / "test_log.json")
    log = ExperimentLog(path)
    record = {
        "config_used": {"stc_os": 15},
        "wfe": 0.42,
        "pf_insample": 1.5,
        "pf_walkforward": 1.2,
    }
    log.log(record)
    log2 = ExperimentLog(path)
    assert len(log2.all()) == 1
    assert log2.all()[0]["wfe"] == 0.42
    assert log2.best_by_wfe()["wfe"] == 0.42


def test_search_strategy_returns_valid_config(tmp_path):
    log = ExperimentLog(str(tmp_path / "test_log.json"))
    space_path = str(tmp_path / "space.json")
    space = {"stc_os": [15, 23], "stc_ob": [83], "stop_atr_mult": [0.50, 0.70]}
    with open(space_path, "w") as f:
        json.dump(space, f)
    config = select_next_config(log, space_path, seed=42)
    assert "stc_os" in config
    assert config["stc_os"] in [15, 23]
    assert config["stc_ob"] == 83
