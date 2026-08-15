"""Tests for the strategy-class MC-DD ceiling in gate v2 (Phase 4).

The MC-95th drawdown ceiling is the one class-dependent gate criterion:
  * intraday_futures (default / "" / beta_harvest) → synced from
    `_gate_v2_helpers.GATE_MC_DD_CORE`/`GATE_MC_DD_ALT` (5% core, 4% alt as of
    2026-07-10; previously a stale hardcoded 6%/7% that had drifted from the
    live routing ceiling's 2026-05-09 tightening — see validate_strategy.py's
    STRATEGY_CLASS_DD comment)
  * equity_swing                                   → 25% core, 30% alt

Every OTHER criterion (PF-CI, p_edge, DSR) is class-independent. These tests lock
in (a) byte-identical behavior for the default/futures path, (b) the wider equity
ceiling, and (c) strict fallback for unknown classes. Class DD affects only how a
verdict SCORES here — it does not authorize routing directly, though the weekly
gate_v2_orchestrator.py cron does persist this validator's verdicts into the same
directory gate_v2_policy.is_ungate_eligible() reads (see validate_strategy.py).
"""
from __future__ import annotations

from backtest._gate_v2_helpers import GATE_MC_DD_ALT, GATE_MC_DD_CORE
from scripts.validate_strategy import (
    DEFAULT_STRATEGY_CLASS,
    STRATEGY_CLASS_DD,
    _dd_ceiling,
    _evaluate_gate_v2,
    _score_core_gate,
)

_CORE_PCT = GATE_MC_DD_CORE * 100  # 5.0
_ALT_PCT = GATE_MC_DD_ALT * 100  # 4.0


def _report(
    *,
    iid_pf_lo: float = 1.30,
    iid_p_edge: float = 0.98,
    block_pf_lo: float = 1.20,
    block_p_edge: float = 0.97,
    mc_95th: float = 4.5,
    dsr: float = 0.25,
) -> dict:
    """Report dict matching validate_strategy.validate() — defaults all-pass (core)."""
    return {
        "bootstrap_iid": {"pf_ci_95_low": iid_pf_lo, "p_positive_edge": iid_p_edge},
        "bootstrap_block": {"pf_ci_95_low": block_pf_lo, "p_positive_edge": block_p_edge},
        "drawdown_mc": {"mc_95th": mc_95th},
        "deflated_sharpe": {"dsr": dsr},
    }


# ── _dd_ceiling map ─────────────────────────────────────────────────────────


def test_dd_ceiling_intraday_futures_matches_gate_v2_helpers():
    assert _dd_ceiling("intraday_futures", "core") == _CORE_PCT
    assert _dd_ceiling("intraday_futures", "alt") == _ALT_PCT


def test_dd_ceiling_empty_string_defaults_to_intraday_futures():
    # main()'s --strategy-class default is "" — must map to the strict ceiling.
    assert _dd_ceiling("", "core") == _CORE_PCT
    assert _dd_ceiling("", "alt") == _ALT_PCT


def test_dd_ceiling_equity_swing_is_wider():
    assert _dd_ceiling("equity_swing", "core") == 25.0
    assert _dd_ceiling("equity_swing", "alt") == 30.0


def test_dd_ceiling_unknown_class_falls_back_to_strictest():
    # A class map must never accidentally LOOSEN a gate.
    assert _dd_ceiling("nonsense", "core") == _dd_ceiling(DEFAULT_STRATEGY_CLASS, "core")
    assert _dd_ceiling("beta_harvest", "core") == _CORE_PCT  # beta_harvest relaxes p_edge, not DD
    assert _dd_ceiling("beta_harvest", "alt") == _ALT_PCT


# ── Default / futures path tracks _gate_v2_helpers ──────────────────────────


def test_futures_dd_between_ceiling_and_25_fails_core_default():
    """A 20% DD fails the futures core (> ceiling, well under equity's 25%)."""
    rpt = _report(mc_95th=20.0)
    for sc in ("", "intraday_futures", "beta_harvest"):
        out = _evaluate_gate_v2(rpt, strategy_class=sc)
        assert out["core_verdict"] == "FAIL", f"class={sc!r} should fail on 20% DD"
        assert any(f"FAIL mc_95th_dd_pct=20.0 > {_CORE_PCT}" in r for r in out["core_reasons"])


def test_default_reasons_carry_no_class_suffix():
    """Default class reasons must be byte-identical to the historical string shape."""
    out = _evaluate_gate_v2(_report(mc_95th=4.5))
    dd_reasons = [r for r in out["core_reasons"] if "mc_95th_dd_pct" in r]
    assert dd_reasons == [f"mc_95th_dd_pct=4.5 <= {_CORE_PCT}"], dd_reasons


def test_passing_futures_report_identical_across_default_spellings():
    rpt = _report(mc_95th=4.5)
    base = _evaluate_gate_v2(rpt)
    for sc in ("", "intraday_futures"):
        assert _evaluate_gate_v2(rpt, strategy_class=sc)["core_reasons"] == base["core_reasons"]


# ── equity_swing widens only the DD ceiling ─────────────────────────────────


def test_equity_swing_passes_dd_that_futures_fails():
    """A 20% DD passes equity_swing core (<25%) while failing futures core."""
    rpt = _report(mc_95th=20.0)
    fut = _evaluate_gate_v2(rpt, strategy_class="intraday_futures")
    eq = _evaluate_gate_v2(rpt, strategy_class="equity_swing")
    assert fut["core_verdict"] == "FAIL"
    assert eq["core_verdict"] == "PASS"
    assert eq["n_core_passed"] == 4
    assert any("<= 25.0 (equity_swing class)" in r for r in eq["core_reasons"])


def test_equity_swing_still_enforces_non_dd_criteria():
    """DSR (class-independent) below the floor fails even at the wide DD ceiling."""
    rpt = _report(mc_95th=20.0, dsr=0.05)  # DSR < 0.10 core floor
    out = _evaluate_gate_v2(rpt, strategy_class="equity_swing")
    assert out["core_verdict"] == "FAIL"
    assert any("FAIL dsr=0.05" in r for r in out["core_reasons"])


def test_equity_swing_dd_above_25_still_fails_core():
    rpt = _report(mc_95th=27.0)
    out = _evaluate_gate_v2(rpt, strategy_class="equity_swing")
    assert out["core_verdict"] == "FAIL"
    assert any("FAIL mc_95th_dd_pct=27.0 > 25.0 (equity_swing class)" in r for r in out["core_reasons"])


# ── score-fn signature back-compat ──────────────────────────────────────────


def test_score_core_gate_default_arg_matches_intraday_futures():
    rpt = _report(mc_95th=6.5)  # over the futures ceiling (5.0)
    passes_default, _ = _score_core_gate(rpt)
    passes_explicit, _ = _score_core_gate(rpt, strategy_class="intraday_futures")
    assert passes_default == passes_explicit
    assert passes_default[2] is False  # DD criterion (index 2) fails at 6.5 > _CORE_PCT


def test_strategy_class_dd_map_shape():
    assert set(STRATEGY_CLASS_DD["intraday_futures"]) == {"core", "alt"}
    assert STRATEGY_CLASS_DD["equity_swing"]["core"] > STRATEGY_CLASS_DD["intraday_futures"]["core"]
