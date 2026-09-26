# Reflex layer

A fast, per-bar decision contract that sits beside the 5-stage debate pipeline.
The debate pipeline is the slow path (research, debate, trader, risk, fund manager).
The reflex is the fast path: one compact snapshot in, one typed judgment out, and
deterministic code decides what that judgment is allowed to do.

**Status: shadow-only.** Nothing here is imported by order routing, the scanner, or
`agents/pipeline.py`. `PolicyOutcome` is an intent. Anything that consumes it later
must still pass `risk/safety_layer.py`, which stays the sole authority on the kill
switch, daily-loss halt, drawdown halt and contract caps.

## Data flow

```
bars / quote / account ──► state.build_snapshot ──► MarketSnapshot (≤400 tokens)
                               │ raises CausalityError on any ts > as_of
                               ▼
                         judge (RuleBasedJudge today; model-backed later)
                               │ reply ──► schema.parse_decision (fails closed → HOLD)
                               ▼
                         policy.evaluate ──► PolicyOutcome {FIRE | HOLD | REDUCE | ESCALATE}
                               │
                               ▼
                         review.review_session (Brier, reliability table, block reasons)
```

## Who owns what

| Decision | Owner | Notes |
|---|---|---|
| Regime, direction, confidence, toxic flow, setup quality | Judge | Typed, bounded, `extra="forbid"` |
| Risk state | Code (`code_risk_state`) | Judge can only make it stricter |
| Entry gate: quality ≥ 2, confidence > 0.80, risk safe, not toxic, quote fresh, flat | Code | |
| Escalate on crisis regime, or a directional call with confidence < 0.60 | Code | ESCALATE means no new risk now. A neutral read is HOLD, not escalate |
| Size | Code | Fractional Kelly (≤ ¼) on the calibrated probability × `drawdown_scale_factor`, capped by `MAX_TRADE_LOSS_USD` and `MAX_CONTRACTS_PER_INSTRUMENT` |
| Reward/risk ratio for Kelly | Code (stop/target geometry) | Never the judge |
| Kill switch / halts | `risk/safety_layer.py` | Unchanged, not duplicated here |

Without a calibrator, size is capped at one contract. A raw model confidence is not a
probability until it has been measured, so Kelly on it is sizing on an unmeasured number.
`analytics.calibration.fit_isotonic_calibration` produces a compatible callable once there
is enough labelled history. Fit it on past sessions only and apply it to later ones.

## Deliberately not built

- **Nightly self-rewrite of the judge or schema.** `review.py` writes a report only.
  Threshold or prompt changes go through a PR and the existing pre-registration and
  forward-test gates. Re-fitting on the same session you then score is in-sample.
- **A third-party "reflex" model or harness.** The judge is a `Protocol`. A model-backed
  judge is the next step, and it has to beat `RuleBasedJudge` on out-of-sample Brier and
  net-of-cost P&L before it replaces it.
- **Exits and pyramiding.** The policy only opens from flat. Open positions belong to
  the existing trade manager.
