from dataclasses import dataclass

from morning_alpha.research.gate_v2_adapter import (
    MorningAlphaGateV2,
    MorningAlphaResearchRun,
    PromotionState,
    advance_promotion_state,
)


@dataclass
class OOS:
    total_trades: int = 100
    profit_factor: float = 1.4
    max_drawdown_pct: float = 0.03
    sharpe_ratio: float = 1.1


def research_run(**overrides):
    values = dict(
        strategy_key="relative_strength_breakout@1.0.0",
        total_historical_trades=200,
        trade_returns_r=tuple([0.5] * 200),
        oos_results=(OOS(), OOS()),
        n_grid_combos=12,
        fixed_params_metrics={"fixed_params_min_pf": 1.25},
        cost_sweep_metrics={"cost_survives_through": "realistic"},
        sparse_strategy_approved=False,
    )
    values.update(overrides)
    return MorningAlphaResearchRun(**values)


def test_adapter_passes_supported_inputs_to_canonical_gate_without_reimplementing_formula():
    captured = {}

    def fake_gate(oos_results, n_grid_combos, fixed_params_metrics, cost_sweep_metrics):
        captured.update(
            oos_results=oos_results,
            n_grid_combos=n_grid_combos,
            fixed_params_metrics=fixed_params_metrics,
            cost_sweep_metrics=cost_sweep_metrics,
        )
        return {"verdict": "PASS", "passed_via": "core", "reasons": ["canonical"]}

    verdict = MorningAlphaGateV2(gate_fn=fake_gate).evaluate(research_run())
    assert captured["n_grid_combos"] == 12
    assert len(captured["oos_results"]) == 2
    assert captured["fixed_params_metrics"] == {"fixed_params_min_pf": 1.25}
    assert captured["cost_sweep_metrics"] == {"cost_survives_through": "realistic"}
    assert verdict.state is PromotionState.GATE_V2_PASSED
    assert verdict.gate_metrics["verdict"] == "PASS"


def test_raw_trade_r_series_is_preserved_and_count_must_match():
    called = False

    def fake_gate(*args):
        nonlocal called
        called = True
        return {"verdict": "PASS"}

    run = research_run(trade_returns_r=tuple([0.5] * 199))
    verdict = MorningAlphaGateV2(gate_fn=fake_gate).evaluate(run)
    assert called is False
    assert verdict.gate_invoked is False
    assert any("trade_returns_r count" in reason for reason in verdict.reasons)


def test_normal_strategy_under_200_trades_does_not_invoke_gate():
    called = False

    def fake_gate(*args):
        nonlocal called
        called = True
        return {"verdict": "PASS"}

    run = research_run(total_historical_trades=199, trade_returns_r=tuple([0.1] * 199))
    verdict = MorningAlphaGateV2(gate_fn=fake_gate).evaluate(run)
    assert called is False
    assert verdict.state is PromotionState.BACKTESTED
    assert any("at least 200" in reason for reason in verdict.reasons)


def test_missing_oos_or_cost_evidence_blocks_gate():
    gate = MorningAlphaGateV2(gate_fn=lambda *args: {"verdict": "PASS"})
    verdict = gate.evaluate(research_run(oos_results=(), cost_sweep_metrics={}))
    assert verdict.gate_invoked is False
    assert any("OOS" in reason for reason in verdict.reasons)
    assert any("cost/slippage" in reason for reason in verdict.reasons)


def test_gate_fail_stays_wfo_validated_not_live():
    gate = MorningAlphaGateV2(
        gate_fn=lambda *args: {"verdict": "FAIL", "passed_via": None, "reasons": ["no edge"]}
    )
    verdict = gate.evaluate(research_run())
    assert verdict.state is PromotionState.WFO_VALIDATED
    assert verdict.gate_verdict == "FAIL"


def test_gate_pass_alone_never_implies_live_eligibility():
    gate = MorningAlphaGateV2(
        gate_fn=lambda *args: {"verdict": "PASS", "passed_via": "alt", "reasons": []}
    )
    verdict = gate.evaluate(research_run())
    assert verdict.state is PromotionState.GATE_V2_PASSED
    assert advance_promotion_state(verdict.state) is PromotionState.GATE_V2_PASSED
    paper = advance_promotion_state(verdict.state, paper_started=True)
    assert paper is PromotionState.PAPER
    forward = advance_promotion_state(paper, forward_validated=True)
    assert forward is PromotionState.FORWARD_VALIDATED
    live = advance_promotion_state(forward, live_approved=True)
    assert live is PromotionState.LIVE_ELIGIBLE
