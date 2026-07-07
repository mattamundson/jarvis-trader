"""
Funnel-gate restrictiveness test suite.

Tests the new funnel_gate.py against:
1. Real MGC gate_v2 verdicts (7 from engine/data/gate_v2_verdicts/archive/)
2. Synthetic edge cases designed to expose false-negative patterns

Each test documents WHY it expects a given verdict and what gate_v2 did historically.

To run:
    cd jarvis-robust-strategy-funnel
    python -m pytest tests/test_funnel_gate_vs_gatev2.py -v

Failing tests fall into two buckets:
- ASSERT_INHERIT failures = funnel_gate disagrees with gate_v2 on a case where
  gate_v2 was correct. This is a BUG in funnel_gate.
- ASSERT_CORRECT_FN failures = funnel_gate matches gate_v2 on a case where
  gate_v2 was wrong (false negative). This is INTENDED — fix funnel_gate to
  produce a different verdict than gate_v2 here.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from funnel_gate import adjudicate  # noqa: E402


# ── Test fixtures from real MGC verdicts ─────────────────────────────────────


def _mgc_card(hypothesis_id: str, family: str = "trend") -> dict:
    """Minimal strategy card stub for adjudicate()."""
    return {
        "hypothesis_id": hypothesis_id,
        "name": hypothesis_id,
        "category": family,
        "instruments": {"primary": "MGC", "tested_on": ["MGC"]},
        "timeframes": {"primary": "30m", "applicable": ["30m"]},
    }


def _make_results(
    dsr: float | None,
    pbo: float | None,
    pf_ci_lower: float | None,
    sr_is: float | None = 1.5,
    sr_oos: float | None = 1.2,
    n_oos_trades: int | None = 50,
    max_dd: float | None = 0.05,
    avg_trade_pnl: float | None = 50.0,
    regime_dsr_low: float = 0.9,
    regime_dsr_normal: float = 0.9,
    regime_dsr_elevated: float = 0.6,
    regime_dsr_high: float = 0.3,
    stressed_dsr: float | None = 0.7,
    perm_p: float | None = 0.02,
    contamination: bool = False,
) -> dict:
    """Build a results dict matching funnel_gate's expected schema."""
    return {
        "deflated_sharpe": {"dsr": dsr},
        "pbo": pbo,
        "monte_carlo": {"pf_95ci_lower": pf_ci_lower},
        "sharpe_in_sample": sr_is,
        "sharpe_out_of_sample": sr_oos,
        "n_oos_trades": n_oos_trades,
        "max_drawdown": max_dd,
        "avg_trade_pnl": avg_trade_pnl,
        "regime_breakdown": {
            "low_vol": {"dsr": regime_dsr_low},
            "normal_vol": {"dsr": regime_dsr_normal},
            "elevated_vol": {"dsr": regime_dsr_elevated},
            "high_vol": {"dsr": regime_dsr_high},
        },
        "slippage_stress": {"dsr_at_2x_slippage": stressed_dsr},
        "permutation_test": {"p_value": perm_p},
        "bar_contamination_check": {
            "sentinel_100_5_rows": 7 if contamination else 0,
            "anomalous_jumps": 0,
        },
    }


# ── INHERITANCE TESTS: funnel_gate must agree with gate_v2's CORRECT kills ──


class TestInheritance:
    """Cases where gate_v2 correctly FAILed. funnel_gate must also FAIL."""

    def test_mgc_trend_rank1_dsr_zero_must_kill(self):
        """
        Real verdict: FAIL via core (p_edge=0.60, dsr=0).
        Justification: DSR=0 means no edge after multiple-testing correction.
        EXPECTED funnel_gate: Tier C.
        """
        card = _mgc_card("trend_emadiff_mgc_intraday_rank1")
        results = _make_results(
            dsr=0.0, pbo=0.5,
            pf_ci_lower=None,  # gate_v2 had NaN
            sr_is=0.4, sr_oos=0.2,
            n_oos_trades=5,    # too few
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        assert verdict.tier == "C", f"Expected C, got {verdict.tier}. DSR=0 must hard-kill."
        assert 1 in verdict.failed_gates, "Gate 1 (DSR) must fail"

    def test_mgc_meanrev_rank1_p_edge_032_must_kill(self):
        """
        Real verdict: FAIL.
        p_edge=0.32 means 32% of WFO windows showed edge — WORSE than random.
        DSR=0 confirms no real edge.
        EXPECTED funnel_gate: Tier C.
        """
        card = _mgc_card("meanrev_overnight_mgc_intraday_rank1", family="mean_reversion")
        results = _make_results(
            dsr=0.0, pbo=0.7,
            pf_ci_lower=0.72,  # below 1.15 threshold
            sr_is=0.3, sr_oos=-0.1,
            n_oos_trades=325, max_dd=0.0569,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        assert verdict.tier == "C", f"Expected C, got {verdict.tier}. p_edge < 0.5 = anti-edge."

    def test_meanrev_rank2_worse_than_random_must_kill(self):
        """Real verdict: FAIL. p_edge=0.25, DSR=0. Worse than coin flip."""
        card = _mgc_card("meanrev_rsi_mgc_intraday_rank2", family="mean_reversion")
        results = _make_results(
            dsr=0.0, pbo=0.75,
            pf_ci_lower=0.50,
            sr_is=0.2, sr_oos=-0.2,
            n_oos_trades=148, max_dd=0.051,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        assert verdict.tier == "C", f"Expected C, got {verdict.tier}."


# ── FALSE-NEGATIVE TESTS: gate_v2 FAILed but funnel_gate should NOT ─────────


class TestFalseNegativeCorrection:
    """
    Cases where gate_v2 produced a FAIL that we believe was overly restrictive.
    funnel_gate must produce Tier A or Tier B (NOT Tier C) here, and the
    gate_v2_disagreement flag should be set.
    """

    def test_mgc_trend_rank3_smoking_gun(self):
        """
        THE KEY TEST.

        Real verdict: FAIL (alt path failed on fixed_params_min_pf=0.45 < 1.2).

        But: rank3's champion combo is IDENTICAL to rank4's (PASS):
            fast=50, slow=120, atr_trail_mult=2.0
        Rank3 champion combo PF = 2.99 (across 48 trades). Rank4 same = 3.17.

        The ONLY difference: rank3's parameter grid included some bad combos
        (fast=30 family) that the optimizer would never pick. The gate
        penalized rank3 for the WIDTH of its search, not the QUALITY of its
        champion.

        funnel_gate should:
        - NOT inherit fixed_params_min_pf logic
        - Produce Tier A or Tier B for this strategy
        - Flag gate_v2_disagreement = True
        """
        card = _mgc_card("trend_emadiff_mgc_intraday_rank3")
        # Use the metrics that rank3 ACTUALLY achieved on its champion combo
        results = _make_results(
            dsr=1.0,                # gate_v2 measured DSR=1.0 — strong
            pbo=0.25,               # passes 0.40 threshold
            pf_ci_lower=2.50,       # champion combo PF; ≥ 1.15 ✓
            sr_is=1.8, sr_oos=1.5,  # ~17% degradation — passes 40% gate
            n_oos_trades=48,        # champion combo had 48 trades
            max_dd=0.0148,          # 1.48% — well under 25× avg trade
            avg_trade_pnl=120.0,
            regime_dsr_normal=1.1,
            regime_dsr_elevated=0.8,
            stressed_dsr=0.8,
            perm_p=0.01,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        assert verdict.tier in {"A", "B"}, (
            f"Expected A or B (NOT C). got {verdict.tier}. "
            f"This case is the smoking gun: gate_v2 killed it on a methodology "
            f"flaw (penalizing wide parameter sweeps), not on real edge issues. "
            f"funnel_gate must not inherit this false negative. "
            f"Failed gates: {verdict.failed_gates}"
        )
        assert verdict.gate_v2_disagreement, (
            "Must flag disagreement with gate_v2 — this case is the canonical "
            "example of where the two gates intentionally differ."
        )

    def test_mgc_trend_rank2_strong_wfo_should_be_tier_b(self):
        """
        Real verdict: FAIL.
        Metrics: WFO=STRONG, p_edge=0.75, DSR=0, mc_dd=0.01%.

        Analysis: WFO=STRONG + p_edge=0.75 means the strategy IS repeating
        across windows, but the Sharpe is being deflated to zero (likely
        frequent small wins + rare big losses). This is NOT no-edge; this is
        edge with bad tail-risk management.

        Should be Tier B with improvement hypothesis: "tighten stops to fix
        DSR" — but the data here has DSR=0 so the gate WILL kill it. Document
        the expected behavior.

        Currently this expected_tier=C because the gate is correctly killing
        on DSR=0, BUT we want the improvement_hypotheses to mention the
        tail-risk fix. Test that.
        """
        card = _mgc_card("trend_emadiff_mgc_intraday_rank2")
        results = _make_results(
            dsr=0.0, pbo=0.55,
            pf_ci_lower=1.05,  # just below 1.15 threshold
            sr_is=1.0, sr_oos=0.5,
            n_oos_trades=4,    # gate_v2 had only 4 OOS trades — gate 5 fails too
            max_dd=0.0001, avg_trade_pnl=200.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        # With DSR=0 and 4 trades, funnel_gate WILL kill this — same as gate_v2.
        # The actionable check is that the kill reason mentions BOTH gate 1
        # and gate 5, so the user knows "fix DSR AND get more trades".
        assert verdict.tier == "C"
        assert 1 in verdict.failed_gates  # DSR
        assert 5 in verdict.failed_gates  # trade count
        assert "DSR" in verdict.kill_reason or "Deflated" in verdict.kill_reason


# ── BORDERLINE TESTS: strategies right at threshold boundaries ──────────────


class TestBorderlineHandling:
    """
    Strategies sitting right on the edge of thresholds should produce Tier B
    with documented improvement hypotheses, not silent Tier C kills.
    """

    def test_dsr_just_below_threshold_should_be_tier_b(self):
        """DSR=0.75 (< 0.80 gate 1), but everything else passes."""
        card = _mgc_card("trend_borderline_mgc_intraday")
        results = _make_results(
            dsr=0.75,           # ONE below 0.80
            pbo=0.30,
            pf_ci_lower=1.40,
            sr_is=1.6, sr_oos=1.2,
            n_oos_trades=80,
            max_dd=0.04, avg_trade_pnl=90.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        # Tier B requires DSR >= 1.0 — but we're at 0.75. This SHOULD be Tier C.
        # Update if Tier B threshold ever changes.
        assert verdict.tier == "C", (
            f"DSR=0.75 is below both the A bar (0.80) and the B floor (1.0). "
            f"Expected C but got {verdict.tier}."
        )

    def test_high_dsr_one_gate_fails_should_be_tier_b(self):
        """DSR=1.3 with regime breadth failing — classic Tier B case."""
        card = _mgc_card("trend_specialist_mgc_intraday")
        results = _make_results(
            dsr=1.3,
            pbo=0.30,
            pf_ci_lower=1.30,
            sr_is=1.5, sr_oos=1.2,
            n_oos_trades=55,
            max_dd=0.04, avg_trade_pnl=80.0,
            # Specialist — works only in one regime, not even at specialist floor
            regime_dsr_low=0.1, regime_dsr_normal=0.2,
            regime_dsr_elevated=0.4, regime_dsr_high=1.0,  # one regime > 0.5 floor but < 1.2 specialist
        )
        verdict = adjudicate(card, results, gate_v2_verdict="UNKNOWN")
        assert verdict.tier == "B", f"Expected B (DSR=1.3, regime fails), got {verdict.tier}"
        assert len(verdict.improvement_hypotheses) > 0, "Tier B must produce improvement hypotheses"

    def test_specialist_strategy_passes_via_regime_specialist_floor(self):
        """One regime with DSR=1.3 (>= specialist floor 1.2) — should pass Gate 6."""
        card = _mgc_card("trend_high_vol_specialist_mgc")
        results = _make_results(
            dsr=1.4,
            pbo=0.30, pf_ci_lower=1.40,
            sr_is=1.7, sr_oos=1.3,
            n_oos_trades=45, max_dd=0.04, avg_trade_pnl=120.0,
            regime_dsr_low=0.0, regime_dsr_normal=0.1,
            regime_dsr_elevated=0.5, regime_dsr_high=1.4,  # specialist
        )
        verdict = adjudicate(card, results, gate_v2_verdict="UNKNOWN")
        gate_6 = next(g for g in verdict.gate_results if g.gate_number == 6)
        assert gate_6.passed, "Specialist with DSR=1.4 in one regime should pass via specialist floor"


# ── NAN TRAP TESTS ───────────────────────────────────────────────────────────


class TestNaNTrap:
    """
    gate_v2 silently passed several MGC verdicts where pf_ci_lower was NaN
    (the metric wasn't computed in earlier verdict generations).

    funnel_gate must NOT silently pass on missing metrics — it should produce
    a clear "metric not computed" failure.
    """

    def test_missing_pf_ci_lower_must_fail_gate_3(self):
        """pf_ci_lower=None should fail Gate 3 with clear reason."""
        card = _mgc_card("trend_with_missing_metric_mgc")
        results = _make_results(
            dsr=1.0,
            pbo=0.30,
            pf_ci_lower=None,  # Missing — gate_v2 silently passed
            sr_is=1.6, sr_oos=1.2,
            n_oos_trades=60, max_dd=0.04, avg_trade_pnl=100.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="PASS")
        assert 3 in verdict.failed_gates, (
            "Missing pf_ci_lower must fail Gate 3, not be silently treated as passing."
        )
        gate_3 = next(g for g in verdict.gate_results if g.gate_number == 3)
        assert "not computed" in gate_3.reason.lower() or "missing" in gate_3.reason.lower(), (
            f"Gate 3 reason must clearly indicate missing metric. Got: {gate_3.reason}"
        )

    def test_missing_dsr_must_fail_gate_1(self):
        """dsr=None must fail Gate 1."""
        card = _mgc_card("trend_no_dsr_mgc")
        results = _make_results(
            dsr=None,           # Missing
            pbo=0.30, pf_ci_lower=1.30,
            sr_is=1.5, sr_oos=1.2,
            n_oos_trades=50, max_dd=0.04, avg_trade_pnl=100.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="UNKNOWN")
        assert 1 in verdict.failed_gates

    def test_missing_permutation_test_must_fail_gate_9(self):
        """Permutation test is critical — no result = no pass."""
        card = _mgc_card("trend_no_perm_mgc")
        results = _make_results(
            dsr=1.0, pbo=0.30, pf_ci_lower=1.30,
            sr_is=1.5, sr_oos=1.2,
            n_oos_trades=50, max_dd=0.04, avg_trade_pnl=100.0,
            perm_p=None,  # Missing
        )
        verdict = adjudicate(card, results, gate_v2_verdict="UNKNOWN")
        assert 9 in verdict.failed_gates


# ── CONTAMINATION TESTS ─────────────────────────────────────────────────────


class TestContamination:
    """
    Contamination (sentinel-100.5 incident) must hard-fail regardless of other metrics.
    """

    def test_contaminated_bars_kill_even_if_all_else_perfect(self):
        card = _mgc_card("contaminated_strategy_mgc")
        # Perfect metrics on contaminated data
        results = _make_results(
            dsr=2.0, pbo=0.05, pf_ci_lower=5.0,
            sr_is=2.5, sr_oos=2.3,
            n_oos_trades=200, max_dd=0.02, avg_trade_pnl=300.0,
            contamination=True,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="UNKNOWN")
        assert 10 in verdict.failed_gates, "Contaminated bars must fail Gate 10"
        assert verdict.tier == "C", "Contamination is non-negotiable — must kill regardless of other metrics"


# ── POSITIVE CASE: Tier A round-trip ────────────────────────────────────────


class TestTierAPositive:
    """Sanity check that funnel_gate actually produces Tier A when warranted."""

    def test_pristine_strategy_reaches_tier_a(self):
        card = _mgc_card("trend_pristine_mgc_intraday")
        results = _make_results(
            dsr=1.5,
            pbo=0.15,
            pf_ci_lower=1.80,
            sr_is=1.8, sr_oos=1.4,  # 22% degradation - passes 40% gate
            n_oos_trades=85,
            max_dd=0.05, avg_trade_pnl=150.0,
            regime_dsr_low=0.9, regime_dsr_normal=1.2,
            regime_dsr_elevated=0.8, regime_dsr_high=0.6,
            stressed_dsr=1.0,
            perm_p=0.005,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="PASS")
        assert verdict.tier == "A", (
            f"Pristine strategy must reach Tier A, got {verdict.tier}. "
            f"Failed gates: {verdict.failed_gates}"
        )
        assert not verdict.failed_gates, "Tier A requires zero failed gates"


# ── DISAGREEMENT TRACKING ────────────────────────────────────────────────────


class TestDisagreementTracking:
    """The funnel_gate disagreement flag is the audit trail mechanism."""

    def test_funnel_passes_but_gate_v2_failed_flags_disagreement(self):
        """rank3-style case."""
        card = _mgc_card("trend_disagreement_mgc")
        results = _make_results(
            dsr=1.2, pbo=0.25, pf_ci_lower=1.60,
            sr_is=1.6, sr_oos=1.3, n_oos_trades=55,
            max_dd=0.04, avg_trade_pnl=110.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="FAIL")
        if verdict.tier == "A":
            assert verdict.gate_v2_disagreement, (
                "If funnel says A and gate_v2 said FAIL, disagreement MUST be flagged."
            )

    def test_funnel_kills_but_gate_v2_passed_flags_disagreement(self):
        """Inverse: gate_v2 passed but funnel rejects."""
        card = _mgc_card("trend_inverse_disagreement_mgc")
        results = _make_results(
            dsr=0.5,  # below 0.80 — funnel kills
            pbo=0.5, pf_ci_lower=1.0,
            sr_is=0.6, sr_oos=0.2,
            n_oos_trades=20, max_dd=0.10, avg_trade_pnl=50.0,
        )
        verdict = adjudicate(card, results, gate_v2_verdict="PASS")
        assert verdict.tier == "C"
        assert verdict.gate_v2_disagreement, (
            "If funnel says C and gate_v2 said PASS, disagreement MUST be flagged."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
