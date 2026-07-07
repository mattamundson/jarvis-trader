"""Tests for gate_v2_orchestrator — aggregates validator outputs into a
persisted consolidated verdict.

Phase 2 implementation of `project_gate_v2_proposal.md`. Orchestrator reads
the research-results file, calls `validate_strategy.validate()` on the
rank-N PnLs, auto-discovers the 3 aux-evidence reports by naming
convention, applies the dual-pathway gate, and writes a single
`{symbol}_{family}_rank{rank}.json` verdict snapshot.

Tests are file-I/O heavy so use tmp_path fixtures. Real validator outputs
from `engine/scripts/validation_reports/` are copied in as ground-truth
shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gate_v2_orchestrator import (
    VerdictSnapshot,
    orchestrate_gate_v2,
    resolve_aux_paths,
)

# ---------------------------------------------------------- #
# Fixtures                                                   #
# ---------------------------------------------------------- #


def _write_results_fixture(
    path: Path, *, rank_params: dict, pnls: list[float], target_rank: int = 7
) -> None:
    """Minimal research-script results JSON; pads list so `target_rank` is
    valid. Only the target_rank entry has real trades — earlier entries are
    harmless placeholders."""
    placeholder = {"params": {}, "pf": 0.0, "n_trades": 0, "trades": []}
    results = [placeholder.copy() for _ in range(target_rank - 1)]
    results.append({
        "params": rank_params,
        "pf": 1.85,
        "n_trades": len(pnls),
        "trades": [{"pnl": p} for p in pnls],
    })
    path.write_text(json.dumps({
        "symbol": "MES",
        "n_combos": len(results),
        "start": "2024-06-01",
        "end": "2026-03-27",
        "interval": "1h",
        "results": results,
    }))


def _write_rolling_wfo(path: Path, verdict: str = "STRONG") -> None:
    path.write_text(json.dumps({
        "symbol": "MES",
        "family": "trend",
        "rank": 7,
        "verdict": verdict,
        "pct_profitable": 82.0,
        "test_pf_distribution": {"median": 2.5},
    }))


def _write_fixed_params(path: Path, min_pf: float = 1.275) -> None:
    path.write_text(json.dumps({
        "symbol": "MES",
        "family": "trend",
        "verdict": "MODERATE",
        "stats": {"min_pf": min_pf, "all_profitable": True, "total_trades": 35},
        "segment_pfs": [min_pf, 2.30],
    }))


def _write_cost_sweep(path: Path, survives: str = "catastrophic") -> None:
    path.write_text(json.dumps({
        "symbol": "MES",
        "family": "trend",
        "rank": 7,
        "edge_survives_through": survives,
        "scenarios": [],
    }))


@pytest.fixture
def synthetic_mes_rank7(tmp_path: Path) -> dict:
    """A plausible 35-trade MES LIVE sample that passes alt gate 5/5 when
    paired with strong aux evidence."""
    reports_dir = tmp_path / "validation_reports"
    reports_dir.mkdir()
    results_file = tmp_path / "mes_trend_search_results.json"

    # 35 per-trade PnLs approximating MES live rank 7 (PF ~1.85, +$870 net)
    wins = [120.0, 85.0, 190.0, 70.0, 45.0, 220.0, 95.0, 140.0,
            180.0, 60.0, 75.0, 110.0, 165.0, 90.0, 55.0, 130.0]
    losses = [-48.0, -52.0, -35.0, -60.0, -44.0, -55.0, -40.0, -38.0,
              -50.0, -45.0, -42.0, -58.0, -36.0, -47.0, -33.0,
              -46.0, -54.0, -41.0, -49.0]
    pnls = wins + losses  # 16 wins + 19 losses = 35 trades; +$1,835 - $943 = ~$892

    _write_results_fixture(results_file,
                           rank_params={"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
                           pnls=pnls)
    _write_rolling_wfo(reports_dir / "MES_trend_rank7_rolling_wfo.json", verdict="STRONG")
    _write_fixed_params(reports_dir / "MES_trend_fixed_params_temporal.json", min_pf=1.275)
    _write_cost_sweep(reports_dir / "MES_trend_rank7_cost_sweep.json", survives="catastrophic")

    return {
        "results_file": results_file,
        "reports_dir": reports_dir,
        "output_dir": tmp_path / "verdicts",
    }


# ---------------------------------------------------------- #
# resolve_aux_paths — naming convention                      #
# ---------------------------------------------------------- #


def test_resolve_aux_paths_uses_naming_convention(tmp_path: Path):
    reports = tmp_path / "validation_reports"
    reports.mkdir()
    (reports / "MES_trend_rank7_rolling_wfo.json").write_text("{}")
    (reports / "MES_trend_fixed_params_temporal.json").write_text("{}")
    (reports / "MES_trend_rank7_cost_sweep.json").write_text("{}")

    paths = resolve_aux_paths(
        reports_dir=reports, symbol="MES", family="trend", rank=7
    )
    assert paths["rolling_wfo"].name == "MES_trend_rank7_rolling_wfo.json"
    assert paths["fixed_params"].name == "MES_trend_fixed_params_temporal.json"
    assert paths["cost_sweep"].name == "MES_trend_rank7_cost_sweep.json"


def test_resolve_aux_paths_returns_none_for_missing_files(tmp_path: Path):
    """Missing aux files should return None rather than raising — the
    orchestrator then writes an alt-UNSCORED verdict."""
    reports = tmp_path / "reports"
    reports.mkdir()
    paths = resolve_aux_paths(
        reports_dir=reports, symbol="MNQ", family="meanrev", rank=1
    )
    assert paths["rolling_wfo"] is None
    assert paths["fixed_params"] is None
    assert paths["cost_sweep"] is None


# ---------------------------------------------------------- #
# orchestrate_gate_v2 — end-to-end                           #
# ---------------------------------------------------------- #


def test_orchestrator_produces_verdict_snapshot(synthetic_mes_rank7):
    """MES rank 7 with all 3 aux signals should produce a VerdictSnapshot
    with verdict + path tags + freshness metadata."""
    snap = orchestrate_gate_v2(
        results_file=synthetic_mes_rank7["results_file"],
        symbol="MES",
        family="trend",
        rank=7,
        reports_dir=synthetic_mes_rank7["reports_dir"],
        output_dir=synthetic_mes_rank7["output_dir"],
        n_resamples=500,  # fast for tests
    )
    assert isinstance(snap, VerdictSnapshot)
    assert snap.symbol == "MES"
    assert snap.family == "trend"
    assert snap.rank == 7
    assert snap.verdict in {"PASS", "FAIL"}
    # Timestamp must be ISO-8601
    assert "T" in snap.created_at
    # Aux freshness map has exactly 3 keys
    assert set(snap.aux_freshness.keys()) == {
        "rolling_wfo", "fixed_params", "cost_sweep",
    }


def test_orchestrator_writes_verdict_json(synthetic_mes_rank7):
    orchestrate_gate_v2(
        results_file=synthetic_mes_rank7["results_file"],
        symbol="MES", family="trend", rank=7,
        reports_dir=synthetic_mes_rank7["reports_dir"],
        output_dir=synthetic_mes_rank7["output_dir"],
        n_resamples=500,
    )
    outfile = synthetic_mes_rank7["output_dir"] / "MES_trend_rank7.json"
    assert outfile.exists()
    doc = json.loads(outfile.read_text())
    # Schema must be reload-able into VerdictSnapshot-equivalent shape
    assert "verdict" in doc
    assert "passed_via" in doc
    assert "core_verdict" in doc
    assert "alt_verdict" in doc
    assert "aux_freshness" in doc
    assert "gate_v2" in doc  # full evaluation result stashed for debugging


def test_orchestrator_falls_back_to_unscored_without_aux(tmp_path):
    """No aux reports present → alt path UNSCORED, overall driven by core."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    results_file = tmp_path / "r.json"
    # Deliberately-weak sample: 10 trades, low edge → core fails
    pnls = [50.0, -45.0, 55.0, -40.0, 60.0, -42.0, 48.0, -38.0, 52.0, -43.0]
    _write_results_fixture(
        results_file,
        rank_params={"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
        pnls=pnls,
    )
    snap = orchestrate_gate_v2(
        results_file=results_file,
        symbol="MES", family="trend", rank=7,
        reports_dir=reports_dir,
        output_dir=tmp_path / "verdicts",
        n_resamples=500,
    )
    assert snap.alt_verdict == "UNSCORED"
    # Freshness map for each channel should be None since files don't exist
    assert snap.aux_freshness["rolling_wfo"] is None


def test_orchestrator_partial_aux_reports_still_unscored(tmp_path):
    """Only 2 of 3 aux reports present → alt UNSCORED (needs all 3)."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _write_rolling_wfo(reports_dir / "MES_trend_rank7_rolling_wfo.json")
    _write_fixed_params(reports_dir / "MES_trend_fixed_params_temporal.json")
    # missing cost_sweep

    results_file = tmp_path / "r.json"
    pnls = [100.0] * 20 + [-50.0] * 15
    _write_results_fixture(
        results_file,
        rank_params={"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
        pnls=pnls,
    )
    snap = orchestrate_gate_v2(
        results_file=results_file,
        symbol="MES", family="trend", rank=7,
        reports_dir=reports_dir,
        output_dir=tmp_path / "verdicts",
        n_resamples=500,
    )
    assert snap.alt_verdict == "UNSCORED"
    assert snap.aux_freshness["rolling_wfo"] is not None
    assert snap.aux_freshness["fixed_params"] is not None
    assert snap.aux_freshness["cost_sweep"] is None


def test_verdict_snapshot_roundtrips_through_json(synthetic_mes_rank7):
    """Written JSON must load back into an equivalent VerdictSnapshot so the
    policy module can read persisted verdicts."""
    snap = orchestrate_gate_v2(
        results_file=synthetic_mes_rank7["results_file"],
        symbol="MES", family="trend", rank=7,
        reports_dir=synthetic_mes_rank7["reports_dir"],
        output_dir=synthetic_mes_rank7["output_dir"],
        n_resamples=500,
    )
    outfile = synthetic_mes_rank7["output_dir"] / "MES_trend_rank7.json"
    doc = json.loads(outfile.read_text())
    reloaded = VerdictSnapshot.from_dict(doc)
    assert reloaded.symbol == snap.symbol
    assert reloaded.verdict == snap.verdict
    assert reloaded.passed_via == snap.passed_via
    assert reloaded.created_at == snap.created_at
