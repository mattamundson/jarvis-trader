"""The Brier scoring rule must be PROPER.

Regression guard for the 2026-07-17 finding: ``compute_brier`` scored
``(|signal| - was_correct)**2`` — conviction vs correctness, not a probability
vs an outcome. Below 0.5 conviction that made being WRONG score better than
being RIGHT, and at 0.5 it was outcome-blind. Because ensemble weight is
``1/(brier+eps)``, the agent who never committed (Corey, |signal|=0.5 always)
earned the largest weight while carrying zero information.

These tests pin the property, not a magic number, so the class cannot regress
into an improper rule again.
"""

from __future__ import annotations

import pytest

from analytics.ic_ensemble import score_forecast


CONVICTIONS = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0]


class TestScoringRuleIsProper:
    @pytest.mark.parametrize("m", CONVICTIONS)
    def test_being_right_scores_strictly_better_than_being_wrong(self, m):
        # This is the exact property the old rule violated below |0.5|.
        right = score_forecast(+m, +100.0)  # called up, went up
        wrong = score_forecast(+m, -100.0)  # called up, went down
        assert right < wrong, (
            f"|signal|={m}: right={right:.4f} must beat wrong={wrong:.4f} "
            "-- an improper rule has regressed"
        )

    @pytest.mark.parametrize("m", CONVICTIONS)
    def test_symmetry_short_side_mirrors_long_side(self, m):
        # A correct short must score identically to an equally-convicted correct long.
        long_right = score_forecast(+m, +100.0)
        short_right = score_forecast(-m, -100.0)
        assert long_right == pytest.approx(short_right)

    @pytest.mark.parametrize("m", CONVICTIONS)
    def test_more_conviction_when_right_scores_no_worse(self, m):
        # Monotonic: being more confident AND right never hurts.
        assert score_forecast(+m, +100.0) <= score_forecast(+0.01, +100.0) + 1e-9

    def test_half_conviction_is_now_scoreable(self):
        # The Corey case: |0.5| used to return 0.25 either way (un-scoreable).
        right = score_forecast(0.5, +1.0)
        wrong = score_forecast(0.5, -1.0)
        assert right == pytest.approx(0.0625)
        assert wrong == pytest.approx(0.5625)
        assert right != wrong

    def test_perfect_forecast_scores_zero(self):
        assert score_forecast(+1.0, +100.0) == pytest.approx(0.0)
        assert score_forecast(-1.0, -100.0) == pytest.approx(0.0)

    def test_maximally_wrong_scores_one(self):
        assert score_forecast(+1.0, -100.0) == pytest.approx(1.0)
        assert score_forecast(-1.0, +100.0) == pytest.approx(1.0)

    def test_no_conviction_is_coinflip_regardless_of_outcome(self):
        # signal=0 -> p=0.5 -> 0.25 either way. Correct: no opinion, no skill.
        assert score_forecast(0.0, +100.0) == pytest.approx(0.25)
        assert score_forecast(0.0, -100.0) == pytest.approx(0.25)

    def test_signal_is_clipped_to_unit_interval(self):
        # Out-of-range signals must not produce a probability outside [0,1].
        assert score_forecast(5.0, +100.0) == pytest.approx(0.0)
        assert score_forecast(-5.0, +100.0) == pytest.approx(1.0)


class TestExpectedScoreIsMinimisedByTruth:
    """Empirical properness: over many outcomes at a fixed true up-probability,
    the report that minimises mean Brier is the truthful one."""

    def test_truthful_report_minimises_expected_score(self):
        true_p = 0.7  # world: 70% up
        # Outcomes proportional to true_p (deterministic, no RNG needed).
        outcomes = [+1.0] * 70 + [-1.0] * 30
        best_signal, best_score = None, 1e9
        for signal in [i / 10.0 for i in range(-10, 11)]:
            mean = sum(score_forecast(signal, o) for o in outcomes) / len(outcomes)
            if mean < best_score:
                best_score, best_signal = mean, signal
        # truthful signal for p=0.7 is signal = 2*0.7 - 1 = 0.4
        assert best_signal == pytest.approx(0.4, abs=0.1001)
