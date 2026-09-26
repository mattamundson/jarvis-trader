"""Reflex policy: deterministic gates, escalation, and Kelly sizing.

Sizing expectations are hand-computed in each test's comment.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from reflex.judge import RuleBasedJudge, build_judge_prompt
from reflex.policy import (
    Action,
    PolicyConfig,
    ReflexLimits,
    code_risk_state,
    evaluate,
)
from reflex.review import ReviewRecord, review_session
from reflex.schema import Direction, ReflexDecision, Regime, RiskState
from reflex.state import AccountState, Bar, Quote, build_snapshot

T0 = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=5)
LIMITS = ReflexLimits(max_contracts=4, max_daily_loss_pct=0.06, max_drawdown_pct=0.20, max_trade_loss_usd=10_000)


def _snap(equity=10_000.0, peak=10_000.0, day_start=10_000.0, position=0, closes=None, quote=None):
    closes = closes or [100.0, 100.0]
    bars = [Bar(T0 + i * STEP, c, c + 1, c - 1, c) for i, c in enumerate(closes)]
    as_of = bars[-1].close_ts
    acct = AccountState(as_of, equity, peak, day_start, position)
    return build_snapshot("MES", as_of, bars, acct, quote=quote(as_of) if quote else None)


def _dec(**kw):
    base = {
        "regime": Regime.TRENDING,
        "direction": Direction.LONG,
        "direction_confidence": 0.9,
        "toxic_flow": False,
        "setup_quality": 3,
        "risk_state": RiskState.SAFE,
    }
    base.update(kw)
    return ReflexDecision(**base)


def _eval(decision, snap=None, limits=LIMITS, reward_risk=1.5, rpc=200.0, calibrator=None, equity=10_000.0):
    return evaluate(decision, snap or _snap(), limits, equity, reward_risk, rpc, calibrator=calibrator)


# ── config validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize("mult", [0.0, 0.26, 1.0])
def test_kelly_multiplier_cannot_exceed_quarter(mult):
    with pytest.raises(ValueError):
        PolicyConfig(kelly_multiplier=mult)


def test_escalate_threshold_must_be_below_fire_threshold():
    with pytest.raises(ValueError):
        PolicyConfig(escalate_below=0.85, min_confidence=0.80)


# ── risk state is code-owned ─────────────────────────────────────────────────


def test_code_risk_state_ladder():
    cfg = PolicyConfig()
    assert code_risk_state(_snap(), LIMITS, cfg) == RiskState.SAFE
    # drawdown accrued on prior days (day_start == equity, so today's P&L is flat)
    # dd 12% of a 20% limit = 0.60 used -> near_limit
    assert code_risk_state(_snap(equity=8_800, peak=10_000, day_start=8_800), LIMITS, cfg) == RiskState.NEAR_LIMIT
    # dd 16% -> 0.80 used -> reduce
    assert code_risk_state(_snap(equity=8_400, peak=10_000, day_start=8_400), LIMITS, cfg) == RiskState.REDUCE
    # same 12% drop all today: -12% day vs 6% limit -> reduce (daily limit binds first)
    assert code_risk_state(_snap(equity=8_800, peak=10_000), LIMITS, cfg) == RiskState.REDUCE
    # day -5% of a 6% limit -> 0.833 used -> reduce
    assert code_risk_state(_snap(equity=9_500, day_start=10_000), LIMITS, cfg) == RiskState.REDUCE


def test_judge_saying_safe_cannot_override_code_near_limit():
    out = _eval(_dec(risk_state=RiskState.SAFE), snap=_snap(equity=8_800, peak=10_000, day_start=8_800), calibrator=lambda p: p)
    assert out.action == Action.HOLD
    assert out.risk_state == RiskState.NEAR_LIMIT
    assert "risk_state=near_limit" in out.reasons


def test_reduce_with_open_position_emits_reduce_and_ignores_judge():
    out = _eval(_dec(), snap=_snap(equity=8_400, peak=10_000, position=1))
    assert out.action == Action.REDUCE and out.contracts == 0


def test_judge_can_tighten_risk():
    out = _eval(_dec(risk_state=RiskState.REDUCE), calibrator=lambda p: p)
    assert out.action == Action.HOLD and out.risk_state == RiskState.REDUCE


# ── escalation + gates ───────────────────────────────────────────────────────


def test_invalid_decision_holds():
    assert _eval(None).action == Action.HOLD


def test_crisis_regime_escalates_even_with_high_confidence():
    out = _eval(_dec(regime=Regime.CRISIS, direction_confidence=0.99))
    assert out.action == Action.ESCALATE and out.contracts == 0


def test_low_confidence_escalates():
    assert _eval(_dec(direction_confidence=0.59)).action == Action.ESCALATE


def test_neutral_low_confidence_holds_without_escalating():
    out = _eval(_dec(direction=Direction.NEUTRAL, direction_confidence=0.5))
    assert out.action == Action.HOLD and "direction_neutral" in out.reasons


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_calibrated_probability_holds(bad):
    out = _eval(_dec(), calibrator=lambda _p: bad)
    assert out.action == Action.HOLD and out.contracts == 0
    assert "invalid_calibrated_probability" in out.reasons


def test_mid_confidence_holds_without_escalating():
    out = _eval(_dec(direction_confidence=0.70))
    assert out.action == Action.HOLD and "confidence<=0.8" in out.reasons


def test_confidence_exactly_at_threshold_does_not_fire():
    assert _eval(_dec(direction_confidence=0.80), calibrator=lambda p: p).action == Action.HOLD


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"direction": Direction.NEUTRAL}, "direction_neutral"),
        ({"toxic_flow": True}, "toxic_flow"),
        ({"setup_quality": 1}, "setup_quality<2"),
    ],
)
def test_entry_gates_block(kw, reason):
    out = _eval(_dec(**kw), calibrator=lambda p: p)
    assert out.action == Action.HOLD and reason in out.reasons


def test_stale_quote_blocks():
    q = lambda as_of: Quote(as_of - timedelta(seconds=30), 99.75, 100.0, 10, 10)  # noqa: E731
    out = _eval(_dec(), snap=_snap(quote=q), calibrator=lambda p: p)
    assert "stale_quote" in out.reasons


def test_open_position_blocks_new_entry():
    out = _eval(_dec(), snap=_snap(position=1), calibrator=lambda p: p)
    assert out.action == Action.HOLD and "position_open" in out.reasons


# ── sizing (hand-computed) ───────────────────────────────────────────────────


def test_kelly_sizing_hand_computed():
    # p=0.55 (calibrated), b=1.5: f* = (1.5*0.55 - 0.45)/1.5 = 0.25
    # quarter Kelly: 0.0625 * $10,000 = $625 ; / $200 per contract = 3.125 -> 3
    out = _eval(_dec(), calibrator=lambda _p: 0.55)
    assert out.kelly_full == pytest.approx(0.25)
    assert out.kelly_applied == pytest.approx(0.0625)
    assert out.action == Action.FIRE and out.side == Direction.LONG and out.contracts == 3


def test_drawdown_scaling_applies():
    # same as above at 6% drawdown -> drawdown_scale_factor 0.75 -> $468.75 / 200 -> 2
    out = _eval(_dec(), snap=_snap(equity=9_400, peak=10_000, day_start=9_400), calibrator=lambda _p: 0.55, equity=10_000)
    assert out.contracts == 2


def test_max_trade_loss_caps_dollar_risk():
    # $625 of Kelly risk capped to $50 ; / $25 per contract -> 2
    limits = ReflexLimits(4, 0.06, 0.20, max_trade_loss_usd=50)
    out = _eval(_dec(), limits=limits, rpc=25.0, calibrator=lambda _p: 0.55)
    assert out.contracts == 2


def test_contract_cap_applies():
    # p=0.9, b=2: f*=(1.8-0.1)/2=0.85 ; x0.25 -> $2,125 / $25 -> 85 -> capped to 4
    out = _eval(_dec(), reward_risk=2.0, rpc=25.0, calibrator=lambda p: p)
    assert out.contracts == LIMITS.max_contracts


def test_uncalibrated_confidence_caps_at_one_contract():
    out = _eval(_dec(), reward_risk=2.0, rpc=25.0)
    assert out.calibrated is False and out.contracts == 1 and "uncalibrated_capped_to_1" in out.reasons


def test_no_edge_after_calibration_holds():
    # judge says 0.9 but history says 0.30 -> f* = (1.5*0.3 - 0.7)/1.5 < 0
    out = _eval(_dec(), calibrator=lambda _p: 0.30)
    assert out.action == Action.HOLD and "no_edge_after_calibration" in out.reasons


def test_size_rounding_to_zero_holds():
    out = _eval(_dec(), rpc=5_000.0, calibrator=lambda _p: 0.55)
    assert out.action == Action.HOLD and out.contracts == 0


@pytest.mark.parametrize("rr,rpc,eq", [(0, 200, 10_000), (1.5, 0, 10_000), (1.5, 200, 0)])
def test_invalid_sizing_inputs_hold(rr, rpc, eq):
    assert _eval(_dec(), reward_risk=rr, rpc=rpc, equity=eq).action == Action.HOLD


# ── end-to-end with the baseline judge ───────────────────────────────────────


def test_rule_based_judge_to_policy_end_to_end():
    closes = [100 + 0.3 * i + (0.05 if i % 2 else -0.05) for i in range(30)]  # steady grind up
    q = lambda as_of: Quote(as_of, closes[-1] - 0.01, closes[-1] + 0.01, 40, 10)  # noqa: E731
    snap = _snap(closes=closes, quote=q)
    decision = asyncio.run(RuleBasedJudge().judge(snap))
    assert decision.regime == Regime.TRENDING
    assert decision.direction == Direction.LONG
    assert decision.setup_quality == 3 and decision.toxic_flow is False
    out = _eval(decision, snap=snap, calibrator=lambda _p: 0.55)
    assert out.action == Action.FIRE and out.side == Direction.LONG


def test_rule_based_judge_flags_crisis_and_wide_spread():
    closes = [100 * (1.02 if i % 2 else 0.98) for i in range(30)]  # ~400 bps bar-to-bar swings
    q = lambda as_of: Quote(as_of, 99.0, 101.0, 10, 10)  # noqa: E731  # 200 bps spread
    decision = asyncio.run(RuleBasedJudge().judge(_snap(closes=closes, quote=q)))
    assert decision.regime == Regime.CRISIS
    assert _eval(decision).action == Action.ESCALATE


def test_judge_prompt_carries_schema_and_snapshot():
    system, user = build_judge_prompt(_snap())
    assert "direction_confidence" in system and '"additionalProperties":false' in system
    assert user.startswith("{") and '"sym":"MES"' in user


# ── review ───────────────────────────────────────────────────────────────────


def test_review_brier_hand_computed():
    out = _eval(_dec())
    recs = [
        ReviewRecord(T0, _dec(direction_confidence=0.9), out, True, T0 + STEP),
        ReviewRecord(T0 + STEP, _dec(direction_confidence=0.8), out, False, T0 + 2 * STEP),
        ReviewRecord(T0 + 2 * STEP, _dec(direction=Direction.NEUTRAL, direction_confidence=0.5), out, None, None),
        ReviewRecord(T0 + 3 * STEP, None, _eval(None), None, None),
    ]
    rep = review_session(recs)
    # ((0.9-1)^2 + (0.8-0)^2) / 2 = (0.01 + 0.64) / 2 = 0.325
    assert rep["brier"] == pytest.approx(0.325)
    assert rep["n_scored"] == 2 and rep["n_decisions"] == 4 and rep["invalid_decisions"] == 1
    bucket = {r["bucket"]: r for r in rep["reliability"]}
    assert bucket["0.9-1.0"]["n"] == 1 and bucket["0.9-1.0"]["hit_rate"] == 1.0
    assert bucket["0.8-0.9"]["n"] == 1 and bucket["0.8-0.9"]["hit_rate"] == 0.0


def test_review_rejects_label_not_after_decision():
    rec = ReviewRecord(T0, _dec(), _eval(_dec()), True, T0)
    with pytest.raises(ValueError):
        review_session([rec])


def test_review_empty_reports_none_not_a_number():
    rep = review_session([])
    assert rep["brier"] is None and rep["escalation_rate"] is None


def test_limits_from_settings_reads_config():
    from config import settings

    lim = ReflexLimits.from_settings()
    assert lim.max_contracts == settings.MAX_CONTRACTS_PER_INSTRUMENT
    assert lim.max_drawdown_pct == settings.MAX_DRAWDOWN_PCT
