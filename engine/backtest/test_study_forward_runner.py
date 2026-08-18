"""Tests for locked-spec forward-evaluation safeguards."""

from pathlib import Path

import pandas as pd
import pytest

from backtest.studies import load_study
from backtest.study_forward_runner import load_forward_data, validate_locked_params


def test_forward_loader_excludes_cutoff_and_prior_rows(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    pd.DataFrame(
        {
            "timestamp": [
                "2026-05-29T23:55:00Z",
                "2026-05-30T00:00:00Z",
                "2026-05-30T00:05:00Z",
            ],
            "open": [1, 2, 3],
            "high": [1, 2, 3],
            "low": [1, 2, 3],
            "close": [1, 2, 3],
            "volume": [1, 1, 1],
        }
    ).to_csv(path, index=False)
    result = load_forward_data(path, "2026-05-30T00:00:00")
    assert len(result) == 1
    assert result.index.min() == pd.Timestamp("2026-05-30T00:05:00Z")
    aware_result = load_forward_data(path, "2026-05-30T00:00:00+00:00")
    assert aware_result.index.equals(result.index)


def test_locked_params_must_match_declared_grid() -> None:
    study = load_study("stc")
    validate_locked_params(study, "go", {"stop_atr": 1.0, "target_atr": 2.0})
    with pytest.raises(ValueError, match="not in the preregistered grid"):
        validate_locked_params(study, "go", {"stop_atr": 0.1, "target_atr": 99.0})
