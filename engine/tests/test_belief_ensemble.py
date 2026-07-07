"""
JARVIS TRADER — Belief-Diverse Trader Ensemble Tests
====================================================
Deterministic verification of the ContestTrade-style tournament selection in
engine/strategies/belief_ensemble.py.

Each test fixes known belief proposals + an IC consensus and asserts the exact
winner, so the selector is provably reproducible and outcome-grounded. The
safety-critical invariants live in the final test class:
  - selection never depends on an LLM,
  - a proposal opposing the IC consensus can never win,
  - ambiguous inputs default to HOLD.
"""

import json

import pytest

from strategies.belief_ensemble import (
    DEFAULT_BELIEFS,
    BeliefProposal,
    ContestJudge,
    TraderBelief,
    load_beliefs,
    run_contest,
)


def _p(name, action, confidence, rr=0.0, signal=0.0):
    return BeliefProposal(
        belief_name=name,
        action=action,
        confidence=confidence,
        rr_ratio=rr,
        signal_score=signal,
    )


class TestBeliefLoading:
    def test_ships_four_personas(self):
        beliefs = load_beliefs()
        names = [b.name for b in beliefs]
        assert "aggressive_momentum" in names
        assert "conservative_mean_reversion" in names
        assert "event_driven" in names
        assert "risk_parity_defensive" in names

    def test_loaded_beliefs_have_prompt_suffix(self):
        for belief in load_beliefs():
            assert isinstance(belief, TraderBelief)
            assert belief.prompt_suffix  # non-empty guidance text

    def test_missing_file_falls_back_to_defaults(self, tmp_path):
        beliefs = load_beliefs(config_path=tmp_path / "does_not_exist.json")
        assert beliefs == list(DEFAULT_BELIEFS)

    def test_malformed_json_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "belief_list.json"
        bad.write_text("{ this is not valid json ", encoding="utf-8")
        assert load_beliefs(config_path=bad) == list(DEFAULT_BELIEFS)

    def test_empty_belief_list_falls_back_to_defaults(self, tmp_path):
        empty = tmp_path / "belief_list.json"
        empty.write_text(json.dumps({"beliefs": []}), encoding="utf-8")
        assert load_beliefs(config_path=empty) == list(DEFAULT_BELIEFS)

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            TraderBelief(name="  ", description="x", prompt_suffix="y")


class TestContestSelection:
    def test_highest_edge_long_proposal_wins_under_long_consensus(self):
        # All three agree LONG with a LONG consensus; winner = max(confidence * rr).
        proposals = [
            _p("aggressive_momentum", "buy", 0.60, rr=2.0),  # 1.20 * align
            _p("conservative_mean_reversion", "buy", 0.90, rr=2.0),  # 1.80 * align  <-- best
            _p("event_driven", "buy", 0.50, rr=1.0),  # 0.50 * align
        ]
        result = run_contest(proposals, consensus_score=0.5)
        assert result.winner is not None
        assert result.winner.belief_name == "conservative_mean_reversion"
        assert result.direction == "LONG"
        assert result.consensus_direction == "LONG"

    def test_contrarian_proposal_cannot_win(self):
        # The strongest proposal is SHORT, but consensus is LONG -> it is
        # disqualified and the weaker aligned LONG proposal wins.
        proposals = [
            _p("aggressive_momentum", "sell", 0.99, rr=5.0),  # disqualified
            _p("event_driven", "buy", 0.40, rr=1.0),  # only admissible directional
        ]
        result = run_contest(proposals, consensus_score=0.6)
        assert result.winner is not None
        assert result.winner.belief_name == "event_driven"
        assert result.direction == "LONG"
        assert result.scores["aggressive_momentum"] == -1.0

    def test_all_hold_returns_hold(self):
        proposals = [
            _p("aggressive_momentum", "hold", 0.0),
            _p("risk_parity_defensive", "hold", 0.0),
        ]
        result = run_contest(proposals, consensus_score=0.4)
        assert result.is_hold
        assert result.winner is None
        assert result.direction == "HOLD"

    def test_all_directional_oppose_consensus_returns_hold(self):
        # Every directional proposal is SHORT but consensus is LONG -> HOLD.
        proposals = [
            _p("aggressive_momentum", "sell", 0.9, rr=3.0),
            _p("event_driven", "sell", 0.8, rr=2.0),
        ]
        result = run_contest(proposals, consensus_score=0.7)
        assert result.is_hold
        assert result.direction == "HOLD"

    def test_short_consensus_selects_best_short(self):
        proposals = [
            _p("aggressive_momentum", "sell", 0.7, rr=1.5),  # 1.05 * align
            _p("conservative_mean_reversion", "sell", 0.7, rr=2.5),  # 1.75 * align <-- best
            _p("event_driven", "buy", 0.99, rr=9.0),  # disqualified (opposes SHORT)
        ]
        result = run_contest(proposals, consensus_score=-0.5)
        assert result.winner.belief_name == "conservative_mean_reversion"
        assert result.direction == "SHORT"
        assert result.scores["event_driven"] == -1.0

    def test_neutral_consensus_allows_either_direction(self):
        # Consensus inside the neutral band: no alignment bonus, no
        # disqualification — pure confidence*rr decides.
        proposals = [
            _p("aggressive_momentum", "buy", 0.6, rr=2.0),  # 1.20
            _p("conservative_mean_reversion", "sell", 0.9, rr=2.0),  # 1.80 <-- best
        ]
        result = run_contest(proposals, consensus_score=0.0)
        assert result.consensus_direction == "HOLD"
        assert result.winner.belief_name == "conservative_mean_reversion"
        assert result.direction == "SHORT"

    def test_ties_break_by_belief_order(self):
        # Identical scores -> the first proposal in the list wins (stable).
        proposals = [
            _p("first", "buy", 0.5, rr=2.0),
            _p("second", "buy", 0.5, rr=2.0),
        ]
        result = run_contest(proposals, consensus_score=0.3)
        assert result.winner.belief_name == "first"

    def test_empty_proposals_returns_hold(self):
        result = run_contest([], consensus_score=0.5)
        assert result.is_hold
        assert result.winner is None

    def test_alignment_bonus_scales_with_consensus_strength(self):
        judge = ContestJudge()
        proposal = _p("x", "buy", 0.5, rr=2.0)  # base = 1.0
        weak = judge.score_proposal(proposal, consensus_score=0.2)
        strong = judge.score_proposal(proposal, consensus_score=0.9)
        assert strong > weak  # stronger consensus -> larger aligned score
        assert weak == pytest.approx(1.0 * (1.0 + 0.2))
        assert strong == pytest.approx(1.0 * (1.0 + 0.9))


class TestSafetyInvariants:
    def test_judge_uses_no_llm(self):
        # The judge module imports nothing from agents/llm — selection is pure
        # arithmetic. This guards against a future regression that sneaks an LLM
        # call into the selection path (forbidden by .claude/rules/safety.md).
        import inspect

        import strategies.belief_ensemble as mod

        src = inspect.getsource(mod)
        for forbidden in ("anthropic", "llm.call", "AdvisorClient", "openai"):
            assert forbidden not in src, f"selection path must not reference {forbidden}"

    def test_selection_is_deterministic_across_runs(self):
        proposals = [
            _p("a", "buy", 0.6, rr=2.0),
            _p("b", "buy", 0.8, rr=1.0),
            _p("c", "sell", 0.9, rr=3.0),
        ]
        results = {run_contest(proposals, 0.5).winner.belief_name for _ in range(50)}
        assert results == {"a"}  # confidence*rr: a=1.2, b=0.8, c=disqualified

    def test_from_decision_lifts_trade_decision_fields(self):
        class _FakeDecision:
            action = "buy"
            confidence = 0.75
            rr_ratio = 2.5
            signal_score = 0.4

        proposal = BeliefProposal.from_decision("momentum", _FakeDecision())
        assert proposal.action == "buy"
        assert proposal.confidence == 0.75
        assert proposal.rr_ratio == 2.5
        assert proposal.direction == "LONG"

    def test_from_decision_handles_dict_and_missing_fields(self):
        proposal = BeliefProposal.from_decision("x", {"action": "sell", "confidence": 0.5})
        assert proposal.action == "sell"
        assert proposal.rr_ratio == 0.0  # missing -> safe default
        assert proposal.direction == "SHORT"
