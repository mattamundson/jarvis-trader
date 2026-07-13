"""PR-C integration tests: MES_VA30 wiring/activation.

Proves the pseudo-symbol registration (MES_VA30_CONFIG in paper_config.py)
end-to-end, against the REAL PAPER_CONFIGS/UNDERLYING_INSTRUMENT entries
(no monkeypatching of the config itself) -- unlike PR-A's
test_aggregates_across_pseudo_symbols_sharing_one_underlying, which predates
this registration existing and simulates it via monkeypatch.

Covers the plan's stated PR-C verification bar:
  1. gate v2 verdict_symbol override (MES_VA30's verdict lives under "MES")
  2. point-value/multiplier fix (MES_VA30 prices at MES's $5/point, not the
     generic default)
  3. combined MES exposure aggregated end-to-end across MES + MES_VA30
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from backtest.gate_v2_policy import is_strategy_authorized
from backtest.paper_config import PAPER_CONFIGS, resolve_underlying
from risk.safety_layer import OrderRequest, SafetyLayer
from utils.position_sizing import get_contract_multiplier


def _write_verdict(
    dir_: Path,
    *,
    symbol: str,
    verdict: str = "PASS",
    passed_via: str = "core",
    family: str = "trend",
    rank: int = 1,
    age_days: float = 0.0,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
    doc = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if passed_via == "core" else "FAIL",
        "alt_verdict": "PASS" if passed_via == "alt" else "UNSCORED",
        "n_core_passed": 4 if passed_via == "core" else 2,
        "n_alt_passed": 5 if passed_via == "alt" else 0,
        "created_at": ts.isoformat(),
        "aux_freshness": {"rolling_wfo": None, "fixed_params": None, "cost_sweep": None},
        "gate_v2": {},
    }
    path = dir_ / f"{symbol}_{family}_rank{rank}.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    from backtest import gate_v2_policy as policy

    monkeypatch.setattr(policy, "_default_verdicts_dir", lambda: tmp_path)
    return tmp_path


class TestVerdictSymbolOverride:
    def test_config_declares_verdict_symbol_mes(self):
        assert PAPER_CONFIGS["MES_VA30"]["verdict_symbol"] == "MES"

    def test_authorized_via_verdict_filed_under_real_underlying(self, tmp_verdicts_dir):
        """A PASS verdict filed under "MES" (sd-116's actual verdict location)
        authorizes the "MES_VA30" pseudo-symbol via the verdict_symbol override."""
        _write_verdict(tmp_verdicts_dir, symbol="MES")

        authorized, reason = is_strategy_authorized("MES_VA30")

        assert authorized is True
        assert reason == "authorized"

    def test_not_authorized_when_only_pseudo_symbol_has_verdict(self, tmp_verdicts_dir):
        """A PASS verdict filed under the pseudo-symbol itself (the wrong key)
        must NOT authorize -- proves the override redirects the lookup rather
        than accepting either key."""
        _write_verdict(tmp_verdicts_dir, symbol="MES_VA30")

        authorized, reason = is_strategy_authorized("MES_VA30")

        assert authorized is False
        assert "verdict lookup: MES" in reason

    def test_not_authorized_when_underlying_verdict_missing(self, tmp_verdicts_dir):
        authorized, reason = is_strategy_authorized("MES_VA30")

        assert authorized is False
        assert "PASS verdict" in reason


class TestPointValueFix:
    def test_multiplier_resolves_through_underlying(self):
        assert resolve_underlying("MES_VA30") == "MES"
        assert get_contract_multiplier("MES_VA30") == get_contract_multiplier("MES") == 5.0

    def test_unregistered_symbol_unaffected(self):
        """Non-regression: a symbol with no UNDERLYING_INSTRUMENT entry
        resolves to itself, not to MES or any other instrument."""
        assert resolve_underlying("NOT_A_REAL_SYMBOL") == "NOT_A_REAL_SYMBOL"


class TestRealInstrumentAggregation:
    """Combined MES exposure across MES (trend) and MES_VA30 (value-area
    re-entry) using the ACTUAL UNDERLYING_INSTRUMENT registration -- proves
    PR-A's aggregation fix and PR-C's real config entry compose correctly,
    not just PR-A's monkeypatched simulation of a future registration."""

    def _mock_db_with_open_trades(self, trades: list[dict]):
        db = Mock()
        db.get_open_trades = Mock(return_value=trades)
        return db

    def test_va30_position_counted_against_mes_trend_order(self, mock_settings):
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES_VA30", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        order = OrderRequest(symbol="MES", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "combined with 1 already open" in result.rejection_reason

    def test_mes_trend_position_counted_against_va30_order(self, mock_settings):
        """Same aggregation, reversed direction: an existing MES trend
        position must be seen by an incoming MES_VA30 order."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        order = OrderRequest(symbol="MES_VA30", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "combined with 1 already open" in result.rejection_reason

    def test_unrelated_symbol_unaffected_by_mes_aggregation(self, mock_settings):
        """Non-regression: MGC's own cap is untouched by MES/MES_VA30
        aggregation -- resolve_underlying() defaulting to identity for
        unlisted symbols must hold for every other existing instrument."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES_VA30", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        order = OrderRequest(symbol="MGC", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is True
