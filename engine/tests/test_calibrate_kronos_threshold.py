"""
Tests for scripts/calibrate_kronos_threshold.py

Run with::

    engine/.venv/Scripts/python -m pytest engine/tests/test_calibrate_kronos_threshold.py -v
"""

from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the calibration script as a module without relying on package discovery.
# pytest runs from engine/ where scripts/ is not on sys.path; importlib.util
# bypasses that by loading from an absolute path.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "calibrate_kronos_threshold.py"

_spec = importlib.util.spec_from_file_location("calibrate_kronos_threshold", _SCRIPT_PATH)
_calib_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_calib_mod)  # type: ignore[union-attr]

_compute_returns_bps = _calib_mod._compute_returns_bps
_mean = _calib_mod._mean
_percentile = _calib_mod._percentile
_std = _calib_mod._std
run_calibration = _calib_mod.run_calibration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_minimal_db(path: Path, rows: dict[str, list[tuple]]) -> None:
    """
    Create a minimal SQLite database with the schema expected by the calibration
    script.  ``rows`` maps symbol -> list of (ts_utc, close) tuples.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY,
            trade_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS market_data_bars (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            ts_utc TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, ts_utc)
        );
        """
    )

    for symbol, bar_rows in rows.items():
        # Add a paper_trade row so the instrument passes presence check
        cur.execute(
            "INSERT OR IGNORE INTO paper_trades "
            "(trade_id, symbol, side, quantity, entry_price, entry_time, status) "
            "VALUES (?, ?, 'BUY', 1, 100.0, '2026-01-01T00:00:00', 'closed')",
            (f"test-{symbol}", symbol),
        )
        for ts, close_price in bar_rows:
            cur.execute(
                "INSERT OR IGNORE INTO market_data_bars "
                "(symbol, interval, ts_utc, open, high, low, close, volume, source, fetched_at) "
                "VALUES (?, '1h', ?, ?, ?, ?, ?, 100.0, 'ibkr', '2026-01-01T00:00:00')",
                (symbol, ts, close_price, close_price * 1.001, close_price * 0.999, close_price),
            )

    conn.commit()
    conn.close()


def _make_ts_sequence(n: int, start: str = "2026-01-01T00:00:00") -> list[str]:
    """Generate ``n`` hourly ISO-8601 timestamps starting from ``start``."""
    from datetime import datetime, timedelta, timezone

    dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    result = []
    for i in range(n):
        result.append((dt + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S"))
    return result


# ---------------------------------------------------------------------------
# test_percentile_computation
# ---------------------------------------------------------------------------


class TestPercentileComputation:
    """Given a known return series, verify percentile and summary statistics."""

    def test_percentiles_known_series(self) -> None:
        # Integers 1..100 inclusive
        data = list(range(1, 101))
        assert _percentile(data, 10) == pytest.approx(10.9, abs=0.1)
        assert _percentile(data, 25) == pytest.approx(25.75, abs=0.1)
        assert _percentile(data, 50) == pytest.approx(50.5, abs=0.1)
        assert _percentile(data, 75) == pytest.approx(75.25, abs=0.1)
        assert _percentile(data, 90) == pytest.approx(90.1, abs=0.1)

    def test_mean_and_std(self) -> None:
        # Sample std (ddof=1): sqrt(sum((x-mean)^2) / (n-1))
        # For [2,4,4,4,5,5,7,9]: mean=5, variance=sum(9+1+1+1+0+0+4+16)/7 = 32/7 ≈ 4.571
        # std ≈ 2.138
        data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        assert _mean(data) == pytest.approx(5.0)
        assert _std(data) == pytest.approx(math.sqrt(32.0 / 7.0), rel=1e-6)

    def test_compute_returns_bps_simple(self) -> None:
        # closes: 100, 101, 102, 103, 104 — horizon=1
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        returns = _compute_returns_bps(closes, horizon=1)
        assert len(returns) == 4
        # log(101/100)*10000 ≈ 99.5 bps
        assert returns[0] == pytest.approx(math.log(101.0 / 100.0) * 10_000, rel=1e-6)

    def test_compute_returns_bps_horizon_5(self) -> None:
        closes = [100.0] * 10 + [105.0]
        returns = _compute_returns_bps(closes, horizon=5)
        # Window from index 5→10: 100→105 ≈ 488 bps
        assert len(returns) == 6
        assert returns[-1] == pytest.approx(math.log(105.0 / 100.0) * 10_000, rel=1e-5)

    def test_compute_returns_bps_too_few_bars(self) -> None:
        closes = [100.0, 101.0, 102.0]
        returns = _compute_returns_bps(closes, horizon=5)
        assert returns == []

    def test_percentile_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _percentile([], 50)

    def test_mean_empty(self) -> None:
        assert _mean([]) == 0.0


# ---------------------------------------------------------------------------
# test_per_instrument_isolation
# ---------------------------------------------------------------------------


class TestPerInstrumentIsolation:
    """Synthetic data for two instruments with different vol levels produces distinct thresholds."""

    def test_distinct_thresholds(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        n = 200  # enough bars for a valid calibration (MIN_BARS_REQUIRED=20, horizon=5)
        timestamps = _make_ts_sequence(n, start="2025-10-01T00:00:00")

        # LOW_VOL: prices drift slowly 100 → 110
        low_vol_closes = [100.0 + i * 0.05 for i in range(n)]

        # HIGH_VOL: prices swing ±2 around 5000
        import math as _math

        high_vol_closes = [5000.0 + 20.0 * _math.sin(i * 0.3) for i in range(n)]

        rows = {
            "LOW_VOL": list(zip(timestamps, low_vol_closes, strict=False)),
            "HIGH_VOL": list(zip(timestamps, high_vol_closes, strict=False)),
        }
        _create_minimal_db(db, rows)

        result = run_calibration(
            db_path=db,
            horizon=5,
            lookback_days=365,  # use full synthetic dataset
            instruments=["LOW_VOL", "HIGH_VOL"],
        )

        lv = result["per_instrument"]["LOW_VOL"]
        hv = result["per_instrument"]["HIGH_VOL"]

        assert lv["status"] == "ok", f"LOW_VOL failed: {lv}"
        assert hv["status"] == "ok", f"HIGH_VOL failed: {hv}"

        # HIGH_VOL should have a larger recommended threshold
        assert hv["recommended_threshold_bps"] > lv["recommended_threshold_bps"], (
            f"Expected HIGH_VOL threshold > LOW_VOL threshold, "
            f"got {hv['recommended_threshold_bps']} vs {lv['recommended_threshold_bps']}"
        )

    def test_thresholds_are_positive(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        n = 50
        timestamps = _make_ts_sequence(n, start="2025-11-01T00:00:00")
        closes = [200.0 + i * 0.1 for i in range(n)]
        rows = {"ALPHA": list(zip(timestamps, closes, strict=False))}
        _create_minimal_db(db, rows)

        result = run_calibration(db_path=db, horizon=5, lookback_days=365, instruments=["ALPHA"])
        assert result["per_instrument"]["ALPHA"]["recommended_threshold_bps"] > 0


# ---------------------------------------------------------------------------
# test_handles_empty_data
# ---------------------------------------------------------------------------


class TestHandlesEmptyData:
    """Instrument with zero rows returns a graceful insufficient_data entry, not a crash."""

    def test_instrument_with_no_bars(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _create_minimal_db(db, {})  # empty — no rows

        # GHOST is in market_data_bars via paper_trades only — no bars
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR IGNORE INTO paper_trades "
            "(trade_id, symbol, side, quantity, entry_price, entry_time, status) "
            "VALUES ('ghost-1', 'GHOST', 'BUY', 1, 100.0, '2026-01-01T00:00:00', 'closed')"
        )
        conn.commit()
        conn.close()

        result = run_calibration(db_path=db, horizon=5, lookback_days=365, instruments=["GHOST"])
        ghost = result["per_instrument"]["GHOST"]
        assert ghost["status"] == "insufficient_data"
        assert "reason" in ghost

    def test_instrument_not_in_db_is_skipped(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _create_minimal_db(db, {})

        # PHANTOM is not registered anywhere — should be silently skipped
        result = run_calibration(db_path=db, horizon=5, lookback_days=365, instruments=["PHANTOM"])
        # PHANTOM should simply not appear in per_instrument (skipped during presence check)
        assert "PHANTOM" not in result["per_instrument"]

    def test_too_few_bars_returns_insufficient(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        n = 3  # fewer than MIN_BARS_REQUIRED + horizon = 25
        timestamps = _make_ts_sequence(n, start="2026-01-01T00:00:00")
        closes = [100.0 + i for i in range(n)]
        _create_minimal_db(db, {"TINY": list(zip(timestamps, closes, strict=False))})

        result = run_calibration(db_path=db, horizon=5, lookback_days=365, instruments=["TINY"])
        tiny = result["per_instrument"]["TINY"]
        assert tiny["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# test_output_json_schema
# ---------------------------------------------------------------------------


class TestOutputJsonSchema:
    """Write calibration output to tmp_path, assert required keys are present."""

    _REQUIRED_TOP_KEYS = {
        "calibrated_at",
        "horizon_bars",
        "lookback_days",
        "per_instrument",
        "global_recommendation_bps",
        "notes",
    }

    _REQUIRED_INSTRUMENT_KEYS_OK = {
        "status",
        "n_bars",
        "mean_return_bps",
        "std_return_bps",
        "percentiles",
        "recommended_threshold_bps",
        "recommendation_method",
    }

    _REQUIRED_PERCENTILE_KEYS = {"p10", "p25", "p50", "p75", "p90"}

    def _build_result(self, tmp_path: Path) -> dict:
        db = tmp_path / "schema_test.db"
        n = 60
        # This class validates output shape, not lookback expiry. Keep its
        # synthetic bars inside the production 365-day window on every run.
        start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        timestamps = _make_ts_sequence(n, start=start)
        closes = [3000.0 + i * 0.5 for i in range(n)]
        _create_minimal_db(db, {"FAKE": list(zip(timestamps, closes, strict=False))})

        return run_calibration(db_path=db, horizon=5, lookback_days=365, instruments=["FAKE"])

    def test_top_level_keys_present(self, tmp_path: Path) -> None:
        result = self._build_result(tmp_path)
        missing = self._REQUIRED_TOP_KEYS - set(result.keys())
        assert not missing, f"Missing top-level keys: {missing}"

    def test_per_instrument_ok_keys(self, tmp_path: Path) -> None:
        result = self._build_result(tmp_path)
        fake = result["per_instrument"]["FAKE"]
        assert fake["status"] == "ok"
        missing = self._REQUIRED_INSTRUMENT_KEYS_OK - set(fake.keys())
        assert not missing, f"Missing instrument keys: {missing}"

    def test_percentile_keys(self, tmp_path: Path) -> None:
        result = self._build_result(tmp_path)
        pcts = result["per_instrument"]["FAKE"]["percentiles"]
        missing = self._REQUIRED_PERCENTILE_KEYS - set(pcts.keys())
        assert not missing, f"Missing percentile keys: {missing}"

    def test_json_serialisable(self, tmp_path: Path) -> None:
        result = self._build_result(tmp_path)
        out_path = tmp_path / "calib.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        with open(out_path) as f:
            loaded = json.load(f)
        assert loaded["per_instrument"]["FAKE"]["status"] == "ok"

    def test_calibrated_at_iso8601(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        result = self._build_result(tmp_path)
        ts = result["calibrated_at"]
        # Should parse without error
        dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
        assert dt.year >= 2026

    def test_global_recommendation_is_float(self, tmp_path: Path) -> None:
        result = self._build_result(tmp_path)
        assert isinstance(result["global_recommendation_bps"], float)
        assert result["global_recommendation_bps"] > 0
