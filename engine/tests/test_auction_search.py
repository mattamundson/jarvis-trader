"""Unit tests for the auction-family gate-v2 search wiring.

Pure / import-level only — no MES data, no Backtester run. The actual backtests
need the engine venv + IBKR cache and are run on the operator's machine
(documented in the PR / plan). These tests protect the contract and the
validator dispatch wiring against regressions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from scripts import (  # noqa: E402
    mes_composite_search,
    mes_saty_search,
    mes_tpo_search,
)
from scripts.auction_search_common import summarize_trades  # noqa: E402

SCRIPTS_DIR = ENGINE_DIR / "scripts"
AUCTION_FAMILIES = ("composite", "saty", "tpo")
VALIDATORS = (
    "rolling_wfo_validator.py",
    "fixed_params_temporal_validator.py",
    "cost_sensitivity_sweep.py",
)


class TestSearchModuleContract:
    def test_modules_expose_run_and_main_and_grid(self):
        for mod in (mes_composite_search, mes_saty_search, mes_tpo_search):
            assert callable(mod._run)
            assert callable(mod._run_combo)
            assert callable(mod.main)
            assert isinstance(mod.GRID, dict) and mod.GRID

    def test_grids_sweep_expected_params(self):
        assert set(mes_composite_search.GRID) == {"entry_threshold", "band_mult"}
        assert set(mes_saty_search.GRID) == {"target_ratio"}
        assert set(mes_tpo_search.GRID) == {"enter", "stop_mult"}

    def test_grids_do_not_sweep_tier3_stc_params(self):
        # STC oversold/overbought are Tier-3 canonical — must never be swept here.
        for mod in (mes_composite_search, mes_saty_search, mes_tpo_search):
            keys = set(mod.GRID)
            assert "stc_oversold" not in keys
            assert "stc_overbought" not in keys


class TestSummarizeTrades:
    def test_empty_ledger(self):
        out = summarize_trades([])
        assert out["total_trades"] == 0
        assert out["pf"] == 0.0
        assert out["trades"] == []

    def test_mixed_pf_and_winrate(self):
        trades = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": 50.0}, {"pnl": -25.0}]
        out = summarize_trades(trades)
        assert out["total_trades"] == 4
        assert out["pf"] == round(150.0 / 75.0, 3)  # 2.0
        assert out["wr"] == 50.0
        assert out["net_pnl"] == 75.0

    def test_no_loss_uses_999_sentinel(self):
        # No-loss combo must report the 999 sentinel so rolling_wfo's pf<900
        # finite-filter and the search sort treat it as trivial, not a winner.
        out = summarize_trades([{"pnl": 10.0}, {"pnl": 20.0}])
        assert out["pf"] == 999.0
        assert out["wr"] == 100.0


class TestValidatorWiring:
    """The three validators must dispatch + offer choices for each auction family."""

    def test_each_validator_dispatches_each_family(self):
        for vfile in VALIDATORS:
            src = (SCRIPTS_DIR / vfile).read_text()
            for fam in AUCTION_FAMILIES:
                assert f'args.family == "{fam}"' in src, f"{vfile} missing dispatch for {fam}"
                assert f"mes_{fam}_search import _run" in src, f"{vfile} missing import for {fam}"

    def test_each_validator_lists_family_choice(self):
        for vfile in VALIDATORS:
            src = (SCRIPTS_DIR / vfile).read_text()
            for fam in AUCTION_FAMILIES:
                assert f'"{fam}"' in src, f"{vfile} missing {fam} in --family choices"
