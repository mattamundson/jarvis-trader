"""
JARVIS TRADER — KAIROS Unit Tests
===================================
Tests for the KAIROS proactive monitoring daemon:
  - ObservationLog (append, read, filter, count)
  - RegimeChangeWatcher (first tick, regime change, same regime)
  - STCCrossoverWatcher (oversold cross, overbought cross, no crossover, missing symbol)
  - RiskLimitWatcher (80% warning, 90% critical, safe levels, empty status)
  - VIXSpikeWatcher (first tick, warning move, critical move, no spike)
  - VolumeAnomalyWatcher (info level, warning level, warmup period)
  - SpreadWideningWatcher (calibration, widening, normal spread)
  - CorrelationBreakWatcher (first tick, divergence, no divergence)
  - KairosDaemon (requires daemon.py — skipped with KAIROS_DAEMON_MISSING marker if absent)

Run with:
    cd engine
    python -m pytest tests/test_kairos.py -v

Async tests require pytest-asyncio:
    pip install pytest-asyncio
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — make the engine package importable from tests/
# ---------------------------------------------------------------------------
_ENGINE_DIR = Path(__file__).parent.parent  # engine/
_PROJECT_ROOT = _ENGINE_DIR.parent  # jarvis-trader/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Daemon availability — if daemon.py does not exist yet, skip those tests
# ---------------------------------------------------------------------------
_DAEMON_AVAILABLE = (_ENGINE_DIR / "kairos" / "daemon.py").exists()
kairos_daemon_missing = pytest.mark.skipif(
    not _DAEMON_AVAILABLE,
    reason="kairos/daemon.py not yet implemented",
)


# ===========================================================================
# ObservationLog
# ===========================================================================


class TestObservationLog:
    """Tests for the JSONL append-only observation log."""

    def test_append_and_read_today(self, tmp_path):
        """Appended observation appears in read_today()."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        obs = Observation(
            timestamp=datetime.now().isoformat(),
            watcher="test_watcher",
            severity=Severity.WARNING,
            message="Test observation",
            data={"price": 5000.0},
            notify=True,
            symbol="MES",
        )
        log.append(obs)
        results = log.read_today()

        assert len(results) == 1
        assert results[0]["watcher"] == "test_watcher"
        assert results[0]["severity"] == "warning"
        assert results[0]["message"] == "Test observation"
        assert results[0]["symbol"] == "MES"
        assert results[0]["notify"] is True
        assert results[0]["data"] == {"price": 5000.0}

    def test_append_multiple_observations(self, tmp_path):
        """Multiple appends are all present in read_today()."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for i in range(3):
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher=f"watcher_{i}",
                severity=Severity.INFO,
                message=f"Observation {i}",
            )
            log.append(obs)

        results = log.read_today()
        assert len(results) == 3
        watchers = [r["watcher"] for r in results]
        assert "watcher_0" in watchers
        assert "watcher_2" in watchers

    def test_read_empty_date_returns_empty_list(self, tmp_path):
        """read_date for a date with no log file returns an empty list."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        results = log.read_date("2020-01-01")
        assert results == []

    def test_read_invalid_date_returns_empty_list(self, tmp_path):
        """read_date with a non-ISO date string returns an empty list gracefully."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        results = log.read_date("not-a-date")
        assert results == []

    def test_get_recent_filters_old_observations(self, tmp_path):
        """get_recent(30) drops observations older than 30 minutes."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))

        # Write an old observation (2 hours ago)
        old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
        old_obs = Observation(
            timestamp=old_ts,
            watcher="old_watcher",
            severity=Severity.INFO,
            message="Old observation",
        )
        # Write a recent observation
        recent_ts = datetime.now().isoformat()
        recent_obs = Observation(
            timestamp=recent_ts,
            watcher="recent_watcher",
            severity=Severity.INFO,
            message="Recent observation",
        )
        log.append(old_obs)
        log.append(recent_obs)

        results = log.get_recent(minutes=30)
        assert len(results) == 1
        assert results[0]["watcher"] == "recent_watcher"

    def test_get_recent_all_within_window(self, tmp_path):
        """get_recent keeps all observations when all are within the window."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for _ in range(3):
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher="w",
                severity=Severity.INFO,
                message="recent",
            )
            log.append(obs)

        results = log.get_recent(minutes=60)
        assert len(results) == 3

    def test_count_by_severity_correct_counts(self, tmp_path):
        """count_by_severity returns correct per-severity totals."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for sev in [Severity.INFO, Severity.WARNING, Severity.WARNING, Severity.CRITICAL]:
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher="test",
                severity=sev,
                message="test",
            )
            log.append(obs)

        counts = log.count_by_severity()
        assert counts["info"] == 1
        assert counts["warning"] == 2
        assert counts["critical"] == 1

    def test_count_by_severity_empty_log(self, tmp_path):
        """count_by_severity on an empty log returns all-zero counts."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        counts = log.count_by_severity()
        assert counts["info"] == 0
        assert counts["warning"] == 0
        assert counts["critical"] == 0

    def test_base_dir_created_automatically(self, tmp_path):
        """ObservationLog creates base_dir hierarchy if it does not exist."""
        from kairos.observation_log import ObservationLog

        nested = tmp_path / "deep" / "nested" / "kairos"
        log = ObservationLog(base_dir=str(nested))
        assert nested.exists()

    def test_severity_values_serialised_as_strings(self, tmp_path):
        """Severity enum values are stored as lowercase strings, not integers."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        obs = Observation(
            timestamp=datetime.now().isoformat(),
            watcher="w",
            severity=Severity.CRITICAL,
            message="m",
        )
        log.append(obs)
        results = log.read_today()
        assert results[0]["severity"] == "critical"  # not "CRITICAL" or 2


# ===========================================================================
# RegimeChangeWatcher
# ===========================================================================


class TestRegimeChangeWatcher:
    """Tests for regime transition detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with no prior state produces no observations."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        snapshot = {"symbols": {"MES": {"regime": "TRENDING_BULL"}}}
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_regime_change(self):
        """Regime transition triggers a WARNING observation."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"regime": "RANGING"}}}

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].symbol == "MES"
        assert result[0].notify is True
        assert "TRENDING_BULL" in result[0].message
        assert "RANGING" in result[0].message

    @pytest.mark.asyncio
    async def test_no_fire_same_regime(self):
        """No observation when regime is unchanged between ticks."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"regime": "TRENDING_BULL"}}}

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_state_updated_after_check(self):
        """_last_regimes is updated after each call, enabling next diff."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        snapshot1 = {"symbols": {"MES": {"regime": "RANGING"}}}
        snapshot2 = {"symbols": {"MES": {"regime": "TRENDING_BEAR"}}}

        await watcher.check(snapshot1)  # sets last = RANGING
        result = await watcher.check(snapshot2)  # RANGING → TRENDING_BEAR

        assert len(result) == 1
        assert "RANGING" in result[0].message

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent(self):
        """Regime changes across multiple symbols each produce their own observations."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        watcher._last_regimes["MNQ"] = "RANGING"

        snapshot = {
            "symbols": {
                "MES": {"regime": "RANGING"},  # changed
                "MNQ": {"regime": "RANGING"},  # unchanged
                "MCL": {"regime": "TRENDING_BEAR"},  # first tick
            }
        }
        result = await watcher.check(snapshot)
        assert len(result) == 1
        assert result[0].symbol == "MES"

    @pytest.mark.asyncio
    async def test_handles_empty_symbols(self):
        """Empty symbols dict returns no observations without error."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        result = await watcher.check({"symbols": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_regime_key(self):
        """Symbol data missing 'regime' key is skipped gracefully."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"stc": 45.0}}}  # no 'regime' key

        result = await watcher.check(snapshot)
        assert result == []


# ===========================================================================
# STCCrossoverWatcher
# ===========================================================================


class TestSTCCrossoverWatcher:
    """Tests for STC overbought/oversold crossover detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with no prior STC produces no observations."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        snapshot = {"symbols": {"MES": {"stc": 45.0}}}
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_oversold_crossover(self):
        """STC dropping from above OS (15) to below OS fires WARNING."""
        from kairos.watchers import Severity, STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0  # above OS=15
        snapshot = {"symbols": {"MES": {"stc": 10.0}}}  # now below OS=15

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].symbol == "MES"
        assert result[0].notify is True
        assert "oversold" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_fires_on_overbought_crossover(self):
        """STC rising from below OB (83) to above OB fires WARNING."""
        from kairos.watchers import Severity, STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 80.0  # below OB=83
        snapshot = {"symbols": {"MES": {"stc": 87.0}}}  # now above OB=83

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert "overbought" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_no_fire_neutral_zone(self):
        """STC staying in the neutral zone (15–83) produces no observations."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 45.0
        snapshot = {"symbols": {"MES": {"stc": 50.0}}}

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_fire_already_oversold_stays_oversold(self):
        """STC already below OS that stays below OS does not re-fire."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 8.0  # already below OS
        snapshot = {"symbols": {"MES": {"stc": 5.0}}}  # still below OS

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_empty_symbols(self):
        """Empty symbols dict returns no observations without error."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        result = await watcher.check({"symbols": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_stc_key(self):
        """Symbol data missing 'stc' key is skipped gracefully."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0
        snapshot = {"symbols": {"MES": {"regime": "RANGING"}}}  # no stc

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_per_symbol_ob_threshold_mnq(self):
        """MNQ uses its custom OB threshold (92.0), not the default (83.0)."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        # MNQ OB = 92.0; set last at 90 (below MNQ threshold) → move to 94
        watcher._last_stc["MNQ"] = 90.0
        snapshot = {"symbols": {"MNQ": {"stc": 94.0}}}

        result = await watcher.check(snapshot)
        # Should fire: 90 <= 92 threshold, and 94 > 92
        assert len(result) == 1
        assert "overbought" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_state_updated_after_check(self):
        """_last_stc is updated after each tick enabling correct diff next call."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0  # above OS
        snapshot1 = {"symbols": {"MES": {"stc": 10.0}}}  # → oversold (fires)
        snapshot2 = {"symbols": {"MES": {"stc": 8.0}}}  # stays oversold (no fire)

        await watcher.check(snapshot1)
        result2 = await watcher.check(snapshot2)
        assert result2 == []  # already in oversold, no new crossover


# ===========================================================================
# RiskLimitWatcher
# ===========================================================================


class TestRiskLimitWatcher:
    """Tests for daily loss limit and drawdown monitoring."""

    @pytest.mark.asyncio
    async def test_fires_warning_at_80pct_daily_loss(self):
        """80–89% daily loss utilisation triggers a WARNING observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -1.6,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 1.0,
            }
        }
        result = await watcher.check(snapshot)

        assert len(result) >= 1
        severities = {o.severity for o in result}
        assert Severity.WARNING in severities or Severity.CRITICAL in severities

    @pytest.mark.asyncio
    async def test_fires_critical_at_90pct_daily_loss(self):
        """90%+ daily loss utilisation triggers a CRITICAL observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -1.85,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 0.5,
            }
        }
        result = await watcher.check(snapshot)

        assert len(result) >= 1
        assert any(o.severity == Severity.CRITICAL for o in result)
        assert any(o.notify is True for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_at_safe_levels(self):
        """Loss well below limit (25% utilisation) produces no observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -0.5,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 1.0,
            }
        }
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_info_on_high_drawdown(self):
        """drawdown_pct > 5% triggers an INFO observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -0.1,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 6.0,
            }
        }
        result = await watcher.check(snapshot)

        assert any(o.severity == Severity.INFO for o in result)

    @pytest.mark.asyncio
    async def test_handles_empty_risk_status(self):
        """Empty risk_status dict is handled gracefully — no observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({"risk_status": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_risk_status_key(self):
        """Missing risk_status key in snapshot is handled gracefully."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_dict_risk_status(self):
        """Non-dict risk_status value is handled gracefully."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({"risk_status": None})
        assert result == []

    @pytest.mark.asyncio
    async def test_no_fire_when_pnl_positive(self):
        """Positive PnL does not trigger daily loss observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": 500.0,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 0.0,
            }
        }
        result = await watcher.check(snapshot)
        assert result == []


# ===========================================================================
# VIXSpikeWatcher
# ===========================================================================


class TestVIXSpikeWatcher:
    """Tests for rapid VIX movement detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First VIX reading produces no observations (no baseline yet)."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({"vix": 18.5})
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_warning_on_large_move(self):
        """VIX moving >= 1.5 pts triggers a WARNING."""
        from kairos.watchers import Severity, VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        # Prime with initial reading
        await watcher.check({"vix": 15.0})
        # Move > 1.5 pts
        result = await watcher.check({"vix": 17.0})

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].notify is True

    @pytest.mark.asyncio
    async def test_fires_critical_on_very_large_move(self):
        """VIX moving >= 3.0 pts triggers a CRITICAL observation."""
        from kairos.watchers import Severity, VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        await watcher.check({"vix": 15.0})
        result = await watcher.check({"vix": 18.5})  # +3.5 pts

        assert len(result) == 1
        assert result[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_no_fire_on_small_move(self):
        """VIX moving < 1.5 pts produces no observations."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        await watcher.check({"vix": 15.0})
        result = await watcher.check({"vix": 15.5})  # +0.5 pts

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_vix(self):
        """Snapshot without 'vix' key returns no observations gracefully."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_none_vix(self):
        """vix=None returns no observations gracefully."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({"vix": None})
        assert result == []


# ===========================================================================
# VolumeAnomalyWatcher
# ===========================================================================


class TestVolumeAnomalyWatcher:
    """Tests for unusual volume detection."""

    @pytest.mark.asyncio
    async def test_no_observation_during_warmup(self):
        """Fewer than 3 bars of history should produce no observations."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        for vol in [1000, 1100]:
            result = await watcher.check({"symbols": {"MES": {"volume": vol}}})
        # During warmup period — should not fire
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_info_at_1_5x_average(self):
        """Volume >= 1.5x rolling average triggers an INFO observation."""
        from kairos.watchers import Severity, VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        # Establish a stable baseline over 10 bars so the spike bar does not
        # dilute the average below the 1.5x threshold when it is appended.
        for _ in range(10):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        # Now send 2000 (2.0x average) — safely above 1.5x even after the
        # spike bar is included in the rolling window.
        result = await watcher.check({"symbols": {"MES": {"volume": 2000}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.INFO for o in result)

    @pytest.mark.asyncio
    async def test_fires_warning_at_2_5x_average(self):
        """Volume >= 2.5x rolling average triggers a WARNING observation."""
        from kairos.watchers import Severity, VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        # Establish a stable baseline over 10 bars so the spike bar does not
        # dilute the average below the 2.5x threshold when it is appended.
        for _ in range(10):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        result = await watcher.check({"symbols": {"MES": {"volume": 5000}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.WARNING for o in result)
        assert any(o.notify is True for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_on_normal_volume(self):
        """Volume close to the rolling average produces no observations."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        for _ in range(5):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        result = await watcher.check({"symbols": {"MES": {"volume": 1050}}})  # 1.05x

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_volume_key(self):
        """Symbol data without 'volume' key is skipped gracefully."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        result = await watcher.check({"symbols": {"MES": {"stc": 45.0}}})
        assert result == []


# ===========================================================================
# SpreadWideningWatcher
# ===========================================================================


class TestSpreadWideningWatcher:
    """Tests for bid-ask spread widening detection."""

    @pytest.mark.asyncio
    async def test_no_observation_during_calibration(self):
        """Fewer than BASELINE_WINDOW bars produces no observations."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        # Only 5 bars — window needs 10
        for _ in range(5):
            result = await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_widened_spread(self):
        """Spread >= 2x the calibrated normal triggers a WARNING."""
        from kairos.watchers import Severity, SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        # Calibrate with BASELINE_WINDOW bars at spread=0.25
        for _ in range(SpreadWideningWatcher._BASELINE_WINDOW):
            await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        # Now send spread=0.55 (2.2x normal)
        result = await watcher.check({"symbols": {"MES": {"spread": 0.55}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.WARNING for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_on_normal_spread(self):
        """Spread within normal range (< 2x) produces no observations."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        for _ in range(SpreadWideningWatcher._BASELINE_WINDOW):
            await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        result = await watcher.check({"symbols": {"MES": {"spread": 0.35}}})  # 1.4x

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_spread_key(self):
        """Symbol data without 'spread' key is skipped gracefully."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        result = await watcher.check({"symbols": {"MES": {"stc": 45.0}}})
        assert result == []


# ===========================================================================
# CorrelationBreakWatcher
# ===========================================================================


class TestCorrelationBreakWatcher:
    """Tests for MES/MNQ correlation divergence detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with prices produces no observation (no return to compute)."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        snapshot = {
            "symbols": {
                "MES": {"price": 5200.0},
                "MNQ": {"price": 18000.0},
            }
        }
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_large_divergence(self):
        """Returns diverging by > 1.5% triggers a WARNING."""
        from kairos.watchers import CorrelationBreakWatcher, Severity

        watcher = CorrelationBreakWatcher()
        # First tick
        await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    "MNQ": {"price": 18000.0},
                }
            }
        )
        # MES up +3%, MNQ flat — divergence 3%
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5150.0},  # +3.0%
                    "MNQ": {"price": 18000.0},  # +0%
                }
            }
        )

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert "MES" in result[0].message
        assert "MNQ" in result[0].message

    @pytest.mark.asyncio
    async def test_no_fire_on_correlated_move(self):
        """Both symbols moving similarly (< 1.5% divergence) produces no observations."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    "MNQ": {"price": 18000.0},
                }
            }
        )
        # Both up ~1%
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5050.0},  # +1.0%
                    "MNQ": {"price": 18180.0},  # +1.0%
                }
            }
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_symbol_data(self):
        """Missing MES or MNQ data returns no observations gracefully."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    # MNQ missing
                }
            }
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_price_key(self):
        """Symbol dict without 'price' field is handled gracefully."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"stc": 45.0},
                    "MNQ": {"stc": 45.0},
                }
            }
        )
        assert result == []


# ===========================================================================
# BaseWatcher — helper method
# ===========================================================================


class TestBaseWatcherHelper:
    """Tests for the _obs() convenience method on BaseWatcher subclasses."""

    def test_obs_returns_observation_with_correct_fields(self):
        """_obs() populates all Observation fields correctly."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        obs = watcher._obs(
            severity=Severity.CRITICAL,
            message="Test message",
            data={"key": "val"},
            notify=True,
            symbol="MCL",
        )
        assert obs.severity == Severity.CRITICAL
        assert obs.message == "Test message"
        assert obs.data == {"key": "val"}
        assert obs.notify is True
        assert obs.symbol == "MCL"
        assert obs.watcher == "regime_change"
        # Timestamp should be a valid ISO datetime string
        datetime.fromisoformat(obs.timestamp)

    def test_obs_default_data_is_empty_dict(self):
        """_obs() without data= uses an empty dict, not None."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        obs = watcher._obs(severity=Severity.INFO, message="test")
        assert obs.data == {}
        assert obs.notify is False
        assert obs.symbol is None


# ===========================================================================
# KairosDaemon — only if daemon.py exists
# ===========================================================================


@kairos_daemon_missing
class TestKairosDaemonStatus:
    """KairosDaemon.get_status() and registration tests."""

    def test_status_before_start(self):
        """get_status() reports running=False and tick_count=0 before start()."""
        from kairos.daemon import KairosDaemon

        config = MagicMock()
        config.KAIROS_TICK_SECONDS = 60
        config.KAIROS_NOTIFY_SEVERITY = "warning"

        daemon = KairosDaemon(config=config)
        status = daemon.get_status()

        assert status["running"] is False
        assert status["tick_count"] == 0

    def test_register_watcher_appears_in_status(self):
        """A registered watcher shows up in get_status()['watchers']."""
        from kairos.daemon import KairosDaemon
        from kairos.watchers import BaseWatcher

        config = MagicMock()
        daemon = KairosDaemon(config=config)

        class MockWatcher(BaseWatcher):
            name = "test_mock"

            async def check(self, snapshot):
                return []

        daemon.register_watcher(MockWatcher())
        status = daemon.get_status()
        assert "test_mock" in status["watchers"]

    @pytest.mark.asyncio
    async def test_tick_calls_all_watchers(self):
        """A single tick() calls check() on every registered watcher."""
        from kairos.daemon import KairosDaemon
        from kairos.watchers import BaseWatcher

        config = MagicMock()
        config.KAIROS_TICK_SECONDS = 60
        config.KAIROS_NOTIFY_SEVERITY = "warning"

        daemon = KairosDaemon(config=config)

        call_log: list[str] = []

        class TrackingWatcher(BaseWatcher):
            name = "tracking"

            async def check(self, snapshot):
                call_log.append("called")
                return []

        daemon.register_watcher(TrackingWatcher())
        await daemon.tick()

        assert len(call_log) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
