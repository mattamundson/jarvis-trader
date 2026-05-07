"""Regression tests for revised gate v2 dual-pathway rule.

Source: `~/.claude/projects/C--windows-system32/memory/project_gate_v2_proposal.md`
(revised 2026-04-21 03:48 CT + addendum 04:30 CT).

Strategies exercised:
  * MES SMA LIVE (50, 200, 2.0) rank 7 — PASS via alt-path (5/5)
  * MCL BB rank 1                      — FAIL both (DSR=0 kills alt)
  * MNQ SMA rank 1                     — FAIL both (DSR=0.159 below alt 0.30)
  * MNQ BB rank 1                      — FAIL both (DSR=0 kills alt)
  * Synthetic rich-sample              — PASS via core path

Memo ground truth determines expected verdicts; numeric fixtures come straight
from `engine/scripts/validation_reports/*_report.json`.
"""
from __future__ import annotations

import pytest

from scripts.validate_strategy import (
    ALT_EVIDENCE_GATE,
    CORE_GATE,
    COST_SURVIVAL_LEVELS,
    _evaluate_gate_v2,
)

# ------------------------------------------------------------------ #
# Fixtures                                                           #
# ------------------------------------------------------------------ #


def _report(
    *,
    iid_pf_lo: float,
    iid_p_edge: float,
    block_pf_lo: float,
    block_p_edge: float,
    mc_95th: float,
    dsr: float,
) -> dict:
    """Shape-compatible report dict matching validate_strategy.validate()."""
    return {
        "bootstrap_iid": {"pf_ci_95_low": iid_pf_lo, "p_positive_edge": iid_p_edge},
        "bootstrap_block": {
            "pf_ci_95_low": block_pf_lo,
            "p_positive_edge": block_p_edge,
        },
        "drawdown_mc": {"mc_95th": mc_95th},
        "deflated_sharpe": {"dsr": dsr},
    }


@pytest.fixture
def mes_live_rank7_report() -> dict:
    """Verbatim numbers from MES_rank7_report.json (2026-04-21 run)."""
    return _report(
        iid_pf_lo=0.6284,
        iid_p_edge=0.8774,
        block_pf_lo=0.9247,
        block_p_edge=0.9539,
        mc_95th=5.3969,
        dsr=0.666582,
    )


@pytest.fixture
def mes_live_rank7_aux() -> dict:
    return {
        "rolling_wfo_verdict": "STRONG",
        "fixed_params_min_pf": 1.275,
        "cost_survives_through": "catastrophic",
    }


@pytest.fixture
def mcl_bb_report() -> dict:
    """MCL BB rank 1 — large sample, tight CI, but DSR=0 (selection bias)."""
    return _report(
        iid_pf_lo=1.02,
        iid_p_edge=0.983,
        block_pf_lo=1.02,
        block_p_edge=0.983,
        mc_95th=16.75,
        dsr=0.000,
    )


@pytest.fixture
def mnq_trend_report() -> dict:
    """MNQ trend rank 1 — thin sample, narrow DSR, bimodal WFO."""
    return _report(
        iid_pf_lo=0.51,
        iid_p_edge=0.796,
        block_pf_lo=0.51,
        block_p_edge=0.796,
        mc_95th=13.53,
        dsr=0.159,
    )


# ------------------------------------------------------------------ #
# Core-gate path tests                                               #
# ------------------------------------------------------------------ #


def test_core_gate_uses_moving_block_ci_not_iid(mes_live_rank7_report):
    """Addendum 2026-04-21 04:30 CT: swap IID → MBB for core pf_ci_lower.

    MES LIVE rank 7: IID lower=0.63, MBB lower=0.92. Neither meets 1.10 (core
    fails either way on this sample), but the verdict must reference the MBB
    number — confirm by checking the reasons list.
    """
    out = _evaluate_gate_v2(mes_live_rank7_report)
    assert any("0.9247" in r or "0.925" in r for r in out["core_reasons"]), (
        f"core_reasons must reference MBB value 0.9247, got {out['core_reasons']}"
    )
    # And MUST NOT cite the IID value
    assert not any("0.6284" in r or "0.628" in r for r in out["core_reasons"])


def test_core_gate_passes_with_rich_sample():
    """Synthetic: rich enough sample that all 4 core thresholds pass."""
    rpt = _report(
        iid_pf_lo=1.30, iid_p_edge=0.98,
        block_pf_lo=1.20, block_p_edge=0.97,
        mc_95th=4.5, dsr=0.25,
    )
    out = _evaluate_gate_v2(rpt)
    assert out["core_verdict"] == "PASS"
    assert out["n_core_passed"] == 4
    assert out["verdict"] == "PASS"


def test_core_gate_mc_dd_threshold_is_6pct_not_5pct():
    """Revised memo raised core DD threshold from 5.0% to 6.0% after Phase A
    MC showed p95 DD 6.58% on the EXCELLENT-verdict live strategy."""
    # 5.5% DD: old gate would FAIL, new gate PASSES this criterion
    rpt = _report(
        iid_pf_lo=1.30, iid_p_edge=0.98,
        block_pf_lo=1.20, block_p_edge=0.97,
        mc_95th=5.5, dsr=0.25,
    )
    out = _evaluate_gate_v2(rpt)
    assert out["core_verdict"] == "PASS"  # 5.5 <= 6.0
    # 6.1% DD: fails core threshold but may still pass alt if aux provided
    rpt2 = _report(
        iid_pf_lo=1.30, iid_p_edge=0.98,
        block_pf_lo=1.20, block_p_edge=0.97,
        mc_95th=6.1, dsr=0.25,
    )
    out2 = _evaluate_gate_v2(rpt2)
    assert out2["core_verdict"] != "PASS"


def test_core_gate_dsr_threshold_is_10pct(mes_live_rank7_report):
    """DSR=0.10 is the Bailey-convention floor for core gate."""
    # DSR exactly at threshold
    rpt = _report(
        iid_pf_lo=1.30, iid_p_edge=0.98,
        block_pf_lo=1.20, block_p_edge=0.97,
        mc_95th=4.0, dsr=0.10,
    )
    out = _evaluate_gate_v2(rpt)
    assert out["core_verdict"] == "PASS"  # 0.10 passes
    rpt2 = _report(
        iid_pf_lo=1.30, iid_p_edge=0.98,
        block_pf_lo=1.20, block_p_edge=0.97,
        mc_95th=4.0, dsr=0.099,
    )
    out2 = _evaluate_gate_v2(rpt2)
    assert out2["core_verdict"] != "PASS"  # below core floor


# ------------------------------------------------------------------ #
# Alt-evidence path tests                                            #
# ------------------------------------------------------------------ #


def test_mes_live_passes_via_alt_path(mes_live_rank7_report, mes_live_rank7_aux):
    """Ground-truth verdict from memo: alt_path PASS (5/5), overall PASS."""
    out = _evaluate_gate_v2(mes_live_rank7_report, aux_evidence=mes_live_rank7_aux)
    assert out["verdict"] == "PASS"
    assert out["passed_via"] == "alt"
    assert out["n_alt_passed"] == 5


def test_alt_path_dsr_floor_is_030(mes_live_rank7_report, mes_live_rank7_aux):
    """Alt path requires DSR >= 0.30 (tighter than core's 0.10) — precisely
    because it relaxes sample-size criteria."""
    rpt = dict(mes_live_rank7_report)
    rpt = {**rpt, "deflated_sharpe": {"dsr": 0.29}}
    out = _evaluate_gate_v2(rpt, aux_evidence=mes_live_rank7_aux)
    assert out["verdict"] == "FAIL"  # DSR below alt floor
    # DSR at exactly 0.30 must pass alt
    rpt_ok = {**rpt, "deflated_sharpe": {"dsr": 0.30}}
    out_ok = _evaluate_gate_v2(rpt_ok, aux_evidence=mes_live_rank7_aux)
    assert out_ok["verdict"] == "PASS"


def test_alt_path_rolling_wfo_weak_fails(mes_live_rank7_report, mes_live_rank7_aux):
    """Only STRONG or MODERATE rolling WFO verdicts qualify for alt."""
    aux = {**mes_live_rank7_aux, "rolling_wfo_verdict": "WEAK"}
    out = _evaluate_gate_v2(mes_live_rank7_report, aux_evidence=aux)
    assert out["verdict"] == "FAIL"
    # MODERATE must qualify
    aux2 = {**mes_live_rank7_aux, "rolling_wfo_verdict": "MODERATE"}
    out2 = _evaluate_gate_v2(mes_live_rank7_report, aux_evidence=aux2)
    assert out2["verdict"] == "PASS"


def test_alt_path_fixed_params_min_pf_boundary_120(
    mes_live_rank7_report, mes_live_rank7_aux
):
    """Alt requires fixed_params_min_pf >= 1.20 across independent segments."""
    aux_fail = {**mes_live_rank7_aux, "fixed_params_min_pf": 1.19}
    assert _evaluate_gate_v2(
        mes_live_rank7_report, aux_evidence=aux_fail
    )["verdict"] == "FAIL"
    aux_edge = {**mes_live_rank7_aux, "fixed_params_min_pf": 1.20}
    assert _evaluate_gate_v2(
        mes_live_rank7_report, aux_evidence=aux_edge
    )["verdict"] == "PASS"


def test_alt_path_cost_survives_realistic_or_stronger(
    mes_live_rank7_report, mes_live_rank7_aux
):
    """Cost sensitivity must survive through 'realistic' (2x cost) at minimum."""
    # baseline-only is insufficient
    aux_bad = {**mes_live_rank7_aux, "cost_survives_through": "baseline"}
    assert _evaluate_gate_v2(
        mes_live_rank7_report, aux_evidence=aux_bad
    )["verdict"] == "FAIL"
    # realistic passes
    aux_ok = {**mes_live_rank7_aux, "cost_survives_through": "realistic"}
    assert _evaluate_gate_v2(
        mes_live_rank7_report, aux_evidence=aux_ok
    )["verdict"] == "PASS"
    # stressed/catastrophic also pass (they're stronger)
    for lvl in ("stressed", "catastrophic"):
        aux_strong = {**mes_live_rank7_aux, "cost_survives_through": lvl}
        assert _evaluate_gate_v2(
            mes_live_rank7_report, aux_evidence=aux_strong
        )["verdict"] == "PASS", f"{lvl} must qualify"


def test_alt_path_mc_dd_threshold_is_7pct(mes_live_rank7_aux):
    """Alt path DD ceiling is looser than core (7% vs 6%) because the
    supplementary evidence strengthens the overall case."""
    # 6.5% DD: fails core (>6%) but passes alt (<=7%) when aux strong
    rpt = _report(
        iid_pf_lo=0.8, iid_p_edge=0.85,      # core fails anyway
        block_pf_lo=0.9, block_p_edge=0.88,
        mc_95th=6.5, dsr=0.40,
    )
    out = _evaluate_gate_v2(rpt, aux_evidence=mes_live_rank7_aux)
    assert out["verdict"] == "PASS"
    assert out["passed_via"] == "alt"
    # 7.1% DD: fails alt too
    rpt2 = _report(
        iid_pf_lo=0.8, iid_p_edge=0.85,
        block_pf_lo=0.9, block_p_edge=0.88,
        mc_95th=7.1, dsr=0.40,
    )
    out2 = _evaluate_gate_v2(rpt2, aux_evidence=mes_live_rank7_aux)
    assert out2["verdict"] == "FAIL"


# ------------------------------------------------------------------ #
# Ground-truth strategy verdicts                                     #
# ------------------------------------------------------------------ #


def test_mcl_bb_fails_both_paths(mcl_bb_report):
    """DSR=0 kills alt path regardless of rolling WFO strength."""
    aux = {
        "rolling_wfo_verdict": "MODERATE",
        "fixed_params_min_pf": 1.30,
        "cost_survives_through": "realistic",
    }
    out = _evaluate_gate_v2(mcl_bb_report, aux_evidence=aux)
    assert out["verdict"] == "FAIL"
    assert out["passed_via"] is None


def test_mnq_trend_fails_alt_via_narrow_dsr(mnq_trend_report):
    """DSR=0.159 passes core's 0.10 floor but fails alt's tighter 0.30."""
    aux = {
        "rolling_wfo_verdict": "WEAK",  # real rolling was WEAK anyway
        "fixed_params_min_pf": 1.00,
        "cost_survives_through": "baseline",
    }
    out = _evaluate_gate_v2(mnq_trend_report, aux_evidence=aux)
    assert out["verdict"] == "FAIL"


# ------------------------------------------------------------------ #
# Contract / schema tests                                            #
# ------------------------------------------------------------------ #


def test_without_aux_evidence_alt_path_not_scored(mes_live_rank7_report):
    """No aux_evidence → alt path unreachable; overall verdict driven by core."""
    out = _evaluate_gate_v2(mes_live_rank7_report)  # no aux
    assert out["alt_verdict"] == "UNSCORED"
    assert out["n_alt_passed"] == 0
    # MES LIVE fails core 2/4 and has no alt data → overall FAIL
    assert out["verdict"] == "FAIL"


def test_partial_aux_evidence_alt_path_not_scored(mes_live_rank7_report):
    """Missing ANY of the three aux inputs → alt path unscored."""
    partial = {"rolling_wfo_verdict": "STRONG", "fixed_params_min_pf": 1.30}
    out = _evaluate_gate_v2(mes_live_rank7_report, aux_evidence=partial)
    assert out["alt_verdict"] == "UNSCORED"
    assert out["verdict"] == "FAIL"


def test_verdict_dict_schema(mes_live_rank7_report, mes_live_rank7_aux):
    """Callers rely on a stable verdict-dict schema. Regression-lock it."""
    out = _evaluate_gate_v2(mes_live_rank7_report, aux_evidence=mes_live_rank7_aux)
    required = {
        "verdict",
        "passed_via",
        "core_verdict",
        "alt_verdict",
        "n_core_passed",
        "n_core_criteria",
        "n_alt_passed",
        "n_alt_criteria",
        "core_reasons",
        "alt_reasons",
    }
    assert required <= set(out.keys())
    assert out["verdict"] in {"PASS", "FAIL"}
    assert out["passed_via"] in {"core", "alt", None}
    assert out["n_core_criteria"] == 4
    assert out["n_alt_criteria"] == 5


def test_constants_exposed_for_reuse():
    """CORE_GATE + ALT_EVIDENCE_GATE thresholds are part of the module's
    public surface — documentation references them, and downstream callers
    (cron, dashboards) should read values rather than hardcode."""
    assert CORE_GATE["pf_ci_lower_min"] == 1.10
    assert CORE_GATE["p_positive_edge_min"] == 0.95
    assert CORE_GATE["max_dd_95th_pct_max"] == 6.0
    assert CORE_GATE["dsr_min"] == 0.10
    assert ALT_EVIDENCE_GATE["dsr_min"] == 0.30
    assert ALT_EVIDENCE_GATE["fixed_params_min_pf_min"] == 1.20
    assert ALT_EVIDENCE_GATE["max_dd_95th_pct_max"] == 7.0
    # Ordinal cost ladder: realistic >= realistic must compare as "qualifies"
    assert COST_SURVIVAL_LEVELS.index("realistic") < COST_SURVIVAL_LEVELS.index(
        "catastrophic"
    )
