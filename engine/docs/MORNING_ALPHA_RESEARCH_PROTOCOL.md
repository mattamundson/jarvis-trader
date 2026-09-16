# JARVIS Morning Alpha Research Protocol

## Principle

Morning Alpha is falsifiable research, not a narrative stock picker. A strategy version is promoted only when evidence survives chronological validation and realistic implementation costs.

## Pre-registration

Before final OOS evaluation, freeze:

- strategy family/version;
- universe and liquidity rules;
- features and thresholds;
- trigger candidates;
- stop/target construction;
- holding horizon;
- cost/slippage assumptions;
- regime filters; and
- promotion thresholds.

Any material rule change creates a new strategy version and a new trial. Failed versions remain in the registry.

## Independent family order

1. `relative_strength_breakout@1.0.0`
2. `sector_rotation@1.0.0`
3. `post_earnings_drift@1.0.0`
4. `momentum_breakout@1.0.0`
5. `pullback_continuation@1.0.0`
6. `gap_continuation@1.0.0`

Do not optimize a blended composite until independent-family evidence is understood.

## Point-in-time correctness

Every decision uses only information with timestamps at or before `as_of`. Universe membership, prices, earnings/news timestamps, sector mappings, and macro/event flags must all be point-in-time safe. A future-data violation invalidates the run.

## Validation sequence

1. Development/in-sample research.
2. Chronological out-of-sample validation.
3. Rolling walk-forward optimization/validation where applicable.
4. Fixed-parameter robustness sweep.
5. Cost/slippage stress.
6. Monte Carlo drawdown/streak analysis.
7. Regime segmentation.
8. Canonical Gate-v2.
9. Paper-forward observation.
10. Separate forward-validation/live-eligibility decision.

## Trial-count / DSR discipline

Deflated Sharpe trial counts must include the actual hypothesis/parameter search campaign, not only the winning grid row. Re-running modified hypotheses increases the effective trial count. Do not reset trial history to obtain a better DSR.

## Costs

At minimum evaluate 0, 2, 5, 10, and 20 bps round-trip sensitivity plus explicit slippage shocks. An edge that vanishes under modest costs is not production-grade.

## Trigger laboratory

Compare exactly versioned variants:

- market open;
- prior-day high/low;
- premarket high/low;
- ORB 5m;
- ORB 15m;
- ORB 30m;
- breakout + retest; and
- VWAP reclaim/rejection.

Do not choose the in-sample maximum without OOS confirmation. Track filtered losers and filtered winners so confirmation thresholds are evaluated as trade-offs, not anecdotes.

## Outcome audit

MFE/MAE begins at actual entry time. If an OHLC bar contains both stop and target with unknown ordering, classify `UNVERIFIED` unless higher-resolution data resolves the sequence. Never assume favorable ordering.

## Promotion lifecycle

```text
IDEA -> BACKTESTED -> WFO_VALIDATED -> GATE_V2_PASSED -> PAPER
     -> FORWARD_VALIDATED -> LIVE_ELIGIBLE
```

`DEGRADED` and `RETIRED` are valid terminal/monitoring states. Gate-v2 PASS alone never authorizes live execution.

## Minimum sample

Normal setup families require at least 200 historical trades before Gate-v2. A sparse-strategy exception must be explicitly approved under the repository's existing Gate-v2 sparse-strategy discipline and documented before evaluation.

## Reproducibility

Every research run should persist:

- code/strategy version;
- as-of range;
- provider/data lineage;
- universe definition;
- trigger version;
- costs/slippage;
- trial count;
- OOS/WFO windows;
- per-trade R series;
- Gate-v2 verdict; and
- failure reasons.
