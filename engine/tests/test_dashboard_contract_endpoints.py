"""Contract-shape tests for dashboard-facing endpoint fixes (Phase 4).

These pin the response SHAPES the frontend reads — the transforms most likely to
regress silently: strategy_c metric key-mapping + percent-unit conversion, and
the readiness-check mapping from ValidationMetrics.compute().
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── strategy_c /metrics: key mapping + percent->fraction (÷100) ────────────────

def test_strategy_c_metrics_maps_keys_and_rescales_units(tmp_path, monkeypatch):
    import routers.strategy_c_router as sc

    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(
        json.dumps(
            {
                # on-disk blocks store percents already ×100
                "full": {
                    "cagr": 17.09, "sharpe": 1.42, "sortino": 2.1, "calmar": 0.9,
                    "max_dd_close_pct": 12.5, "ann_vol": 18.0, "win_rate_pct": 56.0,
                    "final_equity": 24700.0, "n_weeks": 260,
                },
                "is_period": {"cagr": 20.0, "sharpe": 1.6, "max_dd_close_pct": 10.0},
                "oos_period": {"cagr": 15.0, "sharpe": 1.3, "max_dd_close_pct": 14.0},
                "oos_retention": {"sharpe_retention_pct": 81.0, "cagr_retention_pct": 75.0},
                "deflated_sharpe": {"p_value": 0.03},
                "vol_stats": {"mean": 0.1},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sc, "_METRICS_FILE", metrics_file)

    out = asyncio.run(sc.get_metrics())

    # keys renamed to the frontend contract
    assert {"full_period", "in_sample", "out_of_sample"}.issubset(out)
    fp = out["full_period"]
    # percent fields divided by 100 so the frontend's fmtPct (×100) is correct
    assert fp["cagr"] == 0.1709
    assert fp["max_drawdown"] == 0.125   # max_dd_close_pct -> max_drawdown ÷100
    assert fp["volatility"] == 0.18      # ann_vol -> volatility ÷100
    assert fp["win_rate"] == 0.56        # win_rate_pct -> win_rate ÷100
    # non-percent passthrough
    assert fp["sharpe"] == 1.42
    assert fp["final_equity"] == 24700.0
    # retention mapped + rescaled
    oos = out["out_of_sample"]
    assert oos["sharpe_retention"] == 0.81
    assert oos["cagr_retention"] == 0.75
    assert out["in_sample"]["cagr"] == 0.20


def test_strategy_c_metrics_handles_missing_subfields(tmp_path, monkeypatch):
    import routers.strategy_c_router as sc

    metrics_file = tmp_path / "sparse.json"
    metrics_file.write_text(json.dumps({"full": {"sharpe": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(sc, "_METRICS_FILE", metrics_file)

    out = asyncio.run(sc.get_metrics())
    assert out["full_period"]["sharpe"] == 1.0
    assert out["full_period"]["cagr"] is None          # absent -> None, no crash
    assert out["out_of_sample"]["sharpe_retention"] is None


# ── validation /readiness-check: maps compute() -> ReadinessReport ─────────────

def test_readiness_check_emits_frontend_contract(monkeypatch):
    import analytics.validation_metrics as vm
    import routers.validation_router as vr

    canned = {
        "all_targets_met": False,
        "targets_met": {
            "days_30": True, "min_trades_60": False, "win_rate_55pct": False,
            "profit_factor_2_0": True, "sharpe_1_5": False, "drawdown_15pct": True,
            "dsr_0_10": True,
        },
        "metrics": {
            "days_elapsed": 31, "total_trades": 39, "win_rate_pct": "38.5%",
            "profit_factor": 3.26, "sharpe_ratio": 0.9, "max_drawdown_pct": 4.2,
            "dsr": 0.15, "dsr_n_obs": 10,
        },
    }
    monkeypatch.setattr(vm.ValidationMetrics, "compute", lambda self: canned)

    out = asyncio.run(vr.get_readiness_check())

    # top-level ReadinessReport contract
    for key in ("ready_for_live", "all_checks_pass", "checks", "passed", "total", "summary"):
        assert key in out
    assert out["total"] == 7             # PR-10 added the Deflated Sharpe Ratio check
    assert out["passed"] == 4            # days_30 + profit_factor + drawdown + dsr
    assert out["ready_for_live"] is False
    assert out["summary"] == "NOT READY"
    # each check has the exact ReadinessCheck shape
    for c in out["checks"]:
        assert set(c.keys()) == {"name", "passed", "value", "requirement", "critical"}
    by_name = {c["name"]: c for c in out["checks"]}
    assert by_name["Profit Factor"]["passed"] is True
    assert by_name["Win Rate"]["passed"] is False
    assert by_name["Trade Count"]["value"] == "39"
    assert by_name["Deflated Sharpe Ratio"]["passed"] is True


def test_readiness_check_fail_soft_on_compute_error(monkeypatch):
    import analytics.validation_metrics as vm
    import routers.validation_router as vr

    def _boom(self):
        raise RuntimeError("db locked")

    monkeypatch.setattr(vm.ValidationMetrics, "compute", _boom)
    out = asyncio.run(vr.get_readiness_check())
    assert out["ready_for_live"] is False
    assert out["summary"] == "NOT READY"
    assert out["checks"] == []
    assert "error" in out
