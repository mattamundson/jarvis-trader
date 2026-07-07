"""
Unit tests for PositionCorrelationMonitor.
Tests correlation exposure calculation and position sizing rules.
"""

import pytest

from orchestrator.position_correlation import PositionCorrelationMonitor


@pytest.fixture
def monitor():
    """Fixture: standard correlation monitor with MNQ-MES pair."""
    pairs = {
        "MNQ-MES": 0.95,
        "MCL-MNQ": 0.10,
        "MCL-MES": 0.10,
    }
    return PositionCorrelationMonitor(
        correlation_pairs=pairs,
        correlation_threshold=0.80,
        default_max_contracts=2,
        correlated_max_contracts=1,
    )


class TestPositionCorrelationMonitor:
    """Tests for position correlation monitoring."""

    def test_single_open_position_uses_default_max(self, monitor):
        """When only MES is open, max_contracts = default (2)."""
        monitor.update_position("MES", 1)
        assert monitor.get_max_contracts("MES") == 2
        assert monitor.get_max_contracts("MNQ") == 2

    def test_both_correlated_pair_open_reduces_max(self, monitor):
        """When both MES and MNQ are open, max_contracts = correlated (1)."""
        monitor.update_position("MES", 1)
        monitor.update_position("MNQ", 1)
        assert monitor.get_max_contracts("MES") == 1
        assert monitor.get_max_contracts("MNQ") == 1

    def test_low_correlation_pair_unaffected(self, monitor):
        """MCL-MNQ correlation (0.10) is below threshold, no reduction."""
        monitor.update_position("MCL", 1)
        monitor.update_position("MNQ", 1)
        assert monitor.get_max_contracts("MCL") == 2
        assert monitor.get_max_contracts("MNQ") == 2

    def test_mcl_position_with_correlated_pair_open(self, monitor):
        """MCL is not in MNQ-MES pair, so unaffected by their correlation."""
        monitor.update_position("MNQ", 1)
        monitor.update_position("MES", 1)
        monitor.update_position("MCL", 1)
        assert monitor.get_max_contracts("MCL") == 2
        assert monitor.get_max_contracts("MNQ") == 1

    def test_closed_position_no_longer_affects_sizing(self, monitor):
        """Closing a position removes its contribution to correlation rule."""
        monitor.update_position("MES", 1)
        monitor.update_position("MNQ", 1)
        assert monitor.get_max_contracts("MES") == 1

        # Close MNQ
        monitor.update_position("MNQ", 0)
        assert monitor.get_max_contracts("MES") == 2

    def test_get_open_symbols(self, monitor):
        """Correctly tracks which symbols have open positions."""
        assert monitor.get_open_symbols() == set()

        monitor.update_position("MES", 1)
        assert monitor.get_open_symbols() == {"MES"}

        monitor.update_position("MNQ", 2)
        assert monitor.get_open_symbols() == {"MES", "MNQ"}

        monitor.update_position("MES", 0)
        assert monitor.get_open_symbols() == {"MNQ"}

    def test_get_correlation_exposure(self, monitor):
        """Returns correct exposure status."""
        monitor.update_position("MES", 1)
        exposure = monitor.get_correlation_exposure()
        assert exposure["open_count"] == 1
        assert exposure["correlation_reduction_active"] is False

        monitor.update_position("MNQ", 1)
        exposure = monitor.get_correlation_exposure()
        assert exposure["open_count"] == 2
        assert exposure["correlation_reduction_active"] is True

    def test_case_insensitive_symbol_matching(self, monitor):
        """Symbols matched case-insensitively (MES == mes)."""
        monitor.update_position("mes", 1)
        monitor.update_position("mnq", 1)
        assert monitor.get_max_contracts("MES") == 1
        assert monitor.get_max_contracts("MNQ") == 1
