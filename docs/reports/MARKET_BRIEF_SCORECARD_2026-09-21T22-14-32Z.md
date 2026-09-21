# Market Brief Scorecard

Generated: 2026-09-21T22:14:32.169939+00:00  ·  model `market-brief-scorecard-v1`

## Safety

- `mode=ANALYSIS_ONLY` · `orders_enabled=false` · `risk_config_touched=false`

## Aggregate

- Briefs scored: **0**  ·  pending (no outcome yet): **1**

## Pending

- 2026-09-21 ES=F: no realized next session yet

## Limitations

- Scores are only as honest as the ledger; missing briefs bias the sample.
- Small n early on: treat Brier/ skill numbers as directional until n is meaningful.
- Daily-bar outcome labels; no intraday touch scoring yet.

## Machine payload

```json
{
  "aggregate": {
    "n_pending": 1,
    "n_scored": 0
  },
  "generated_at": "2026-09-21T22:14:32.169939+00:00",
  "limitations": [
    "Scores are only as honest as the ledger; missing briefs bias the sample.",
    "Small n early on: treat Brier/ skill numbers as directional until n is meaningful.",
    "Daily-bar outcome labels; no intraday touch scoring yet."
  ],
  "model_version": "market-brief-scorecard-v1",
  "pending": [
    {
      "continuation": 55.6,
      "date": "2026-09-21",
      "failure": 18.5,
      "model_version": "market-brief-scorecard-v1",
      "reason": "no realized next session yet",
      "recorded_at": "2026-09-21T22:08:00.007313+00:00",
      "rotation": 25.9,
      "safety": {
        "mode": "ANALYSIS_ONLY",
        "orders_enabled": false,
        "risk_config_touched": false
      },
      "signal_close": 7829.25,
      "signal_low": 7713.75,
      "source": "cli",
      "state": "ath_close_lowvol_accel_gt2",
      "symbol": "ES=F"
    }
  ],
  "safety": {
    "mode": "ANALYSIS_ONLY",
    "orders_enabled": false,
    "risk_config_touched": false
  },
  "scored": []
}
```
