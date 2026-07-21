"""Tests for GATE_V2_ENFORCE_CACHE_TRUST in `_find_latest_cache`.

Three fail-open paths existed before this flag, all of which returned a cache
the completeness checker had already judged unsound:

1. the check was skipped entirely when the directory held ONE candidate --
   precisely the case that shipped the 57%-complete MES 15m file on 2026-07-21,
2. the `fallback` branch warned and returned the holed file anyway,
3. `except Exception` warned and returned the file when the check itself failed.

Default remains OFF, so these assert both the dormant and the enforcing shape.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest._gate_v2_helpers import (
    UntrustworthyCacheError,
    _find_latest_cache,
    _is_cache_trust_enforced,
)

UTC = timezone.utc
FLAG = "GATE_V2_ENFORCE_CACHE_TRUST"


def _write_holed_cache(directory: Path, name: str) -> Path:
    """A cache with an unexplained multi-weekday hole."""
    path = directory / name
    rows = []
    start = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
    for i in range(40):  # ~2 days of hourly bars
        rows.append((start + timedelta(hours=i), 6000.0 + i))
    resume = start + timedelta(days=21)  # 3-week unexplained hole
    for i in range(40):
        rows.append((resume + timedelta(hours=i), 6100.0 + i))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for ts, close in rows:
            w.writerow([ts.isoformat(), close, close, close, close, 100])
    return path


@pytest.fixture
def holed_dir(tmp_path):
    _write_holed_cache(tmp_path, "MES_2026-03-02_2026-03-25_1h.csv")
    return tmp_path


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    assert _is_cache_trust_enforced() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_flag_truthy_values(monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    assert _is_cache_trust_enforced() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_flag_falsey_values(monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    assert _is_cache_trust_enforced() is False


def test_dormant_by_default_returns_holed_cache(holed_dir, monkeypatch):
    """Default OFF must preserve the historical warn-and-continue behavior."""
    monkeypatch.delenv(FLAG, raising=False)
    result = _find_latest_cache(holed_dir, "MES", "_1h.csv")
    assert result.name == "MES_2026-03-02_2026-03-25_1h.csv"


def test_enforced_refuses_holed_cache(holed_dir, monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    with pytest.raises(UntrustworthyCacheError, match="suspicious gap"):
        _find_latest_cache(holed_dir, "MES", "_1h.csv")


def test_single_candidate_directory_is_still_inspected(holed_dir, monkeypatch):
    """Regression: the old `len(candidates) > 1` guard skipped this entirely."""
    assert len(list(holed_dir.glob("MES_*_1h.csv"))) == 1
    monkeypatch.setenv(FLAG, "1")
    with pytest.raises(UntrustworthyCacheError):
        _find_latest_cache(holed_dir, "MES", "_1h.csv")


def test_enforced_refuses_when_the_check_itself_fails(holed_dir, monkeypatch):
    """Cannot evaluate trust -> cannot assert it. Never a silent pass."""
    monkeypatch.setenv(FLAG, "1")

    def _boom(*args, **kwargs):
        raise OSError("simulated inspection failure")

    monkeypatch.setattr("backtest.cache_completeness.find_trustworthy_cache", _boom)
    with pytest.raises(UntrustworthyCacheError, match="completeness check failed"):
        _find_latest_cache(holed_dir, "MES", "_1h.csv")


def test_dormant_still_tolerates_a_failing_check(holed_dir, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)

    def _boom(*args, **kwargs):
        raise OSError("simulated inspection failure")

    monkeypatch.setattr("backtest.cache_completeness.find_trustworthy_cache", _boom)
    assert _find_latest_cache(holed_dir, "MES", "_1h.csv").name.startswith("MES_")


def test_missing_cache_still_raises_filenotfound(tmp_path, monkeypatch):
    """Enforcement must not mask the pre-existing not-found contract."""
    monkeypatch.setenv(FLAG, "1")
    with pytest.raises(FileNotFoundError):
        _find_latest_cache(tmp_path, "MES", "_1h.csv")
