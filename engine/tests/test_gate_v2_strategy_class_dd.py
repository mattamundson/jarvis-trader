"""Tests for the strategy-class MC-DD ceiling in gate v2 (Phase 4).

The MC-95th drawdown ceiling is the one class-dependent gate criterion:
  * intraday_futures (default / "" / beta_harvest) → 6% core, 7% alt (unchanged)
  * equity_swing                                   → 25% core, 30% alt

Every OTHER criterion (PF-CI, p_edge, DSR) is class-independent. These tests lock
in (a) byte-identical behavior for the default/futures path, (b) the wider equity
ceiling, and (c) strict fallback for unknown classes. Class DD affects only how a
verdict SCORES here — it does not authorize routing.
"""
from __future__ import annotations

from scripts.validate_strategy import (
    DEFAULT_STRATEGY_CLASS,
    STRATEGY_CLASS_DD,
    _dd_ceiling,
    _evaluate_gate_v2,
    _score_core_gate,
)


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


def test_dd_ceiling_intraday_futures_is_6_and_7():
    assert _dd_ceiling("intraday_futures", "core") == 6.0
    assert _dd_ceiling("intraday_futures", "alt") == 7.0


def test_dd_ceiling_empty_string_defaults_to_intraday_futures():
    # main()'s --strategy-class default is "" — must map to the strict ceiling.
    assert _dd_ceiling("", "core") == 6.0
    assert _dd_ceiling("", "alt") == 7.0


def test_dd_ceiling_equity_swing_is_wider():
    assert _dd_ceiling("equity_swing", "core") == 25.0
    assert _dd_ceiling("equity_swing", "alt") == 30.0


def test_dd_ceiling_unknown_class_falls_back_to_strictest():
    # A class map must never accidentally LOOSEN a gate.
    assert _dd_ceiling("nonsense", "core") == _dd_ceiling(DEFAULT_STRATEGY_CLASS, "core")
    assert _dd_ceiling("beta_harvest", "core") == 6.0  # beta_harvest relaxes p_edge, not DD
    assert _dd_ceiling("beta_harvest", "alt") == 7.0


# ── Default / futures path is unchanged ─────────────────────────────────────


def test_futures_dd_between_6_and_25_fails_core_default():
    """A 20% DD fails the futures core (>6%) — the pre-change behavior."""
    rpt = _report(mc_95th=20.0)
    for sc in ("", "intraday_futures", "beta_harvest"):
        out = _evaluate_gate_v2(rpt, strategy_class=sc)
        assert out["core_verdict"] == "FAIL", f"class={sc!r} should fail on 20% DD"
        assert any("FAIL mc_95th_dd_pct=20.0 > 6.0" in r for r in out["core_reasons"])


def test_default_reasons_carry_no_class_suffix():
    """Default class reasons must be byte-identical to the historical string."""
    out = _evaluate_gate_v2(_report(mc_95th=4.5))
    dd_reasons = [r for r in out["core_reasons"] if "mc_95th_dd_pct" in r]
    assert dd_reasons == ["mc_95th_dd_pct=4.5 <= 6.0"], dd_reasons


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
    rpt = _report(mc_95th=6.5)  # just over the futures ceiling
    passes_default, _ = _score_core_gate(rpt)
    passes_explicit, _ = _score_core_gate(rpt, strategy_class="intraday_futures")
    assert passes_default == passes_explicit
    assert passes_default[2] is False  # DD criterion (index 2) fails at 6.5 > 6.0


def test_strategy_class_dd_map_shape():
    assert set(STRATEGY_CLASS_DD["intraday_futures"]) == {"core", "alt"}
    assert STRATEGY_CLASS_DD["equity_swing"]["core"] > STRATEGY_CLASS_DD["intraday_futures"]["core"]
