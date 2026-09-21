# Market Brief — Measured Base Rates

Generated: 2026-09-21T22:14:15.343124+00:00  ·  model `market-brief-base-rates-v1`

## Safety

- `mode=ANALYSIS_ONLY` · `orders_enabled=false` · `risk_config_touched=false`
- No broker, order routing, risk config, kill-switch, .env or symbol-gate change.

## Today's state

- Date: `2026-09-21`  ·  ES close `7830.75`  ·  low `7829.00`
- New ATH close: `True`  ·  VIX `14.869999885559082`  ·  5d accel `2.7%`
- Matched state: `ath_close_lowvol_accel_gt2`  (n=27)

## Probability block (next session)

| Outcome | Probability |
|---|---:|
| Continuation (close higher) | **55.6%** |
| Rotation (down close, holds low) | **25.9%** |
| Failure (down close, breaks low) | **18.5%** |
| Sum | 100.0% |

## Context

| Metric | Value |
|---|---:|
| P(higher high next session) | 81.5% |
| P(gaps below today's open) | 7.4% |
| P(trades below today's low) | 18.5% |
| P(up 5 sessions) | 48.1% |
| Median 5-session return | -0.09% |
| Median 5-session adverse excursion | -0.76% |

## State table (causal, no lookahead)

| State | n | Cont. | Rot. | Fail. | P(higher high) | P(gap down) | P(up 5d) | med 5d | med MAE5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_days | 1253 | 52.6 | 14.0 | 33.4 | 55.4 | 46.0 | 58.3 | 0.37 | -1.23 |
| not_ath_close | 1099 | 52.3 | 12.0 | 35.7 | 52.4 | 51.5 | 58.1 | 0.39 | -1.35 |
| ath_close_hivol | 58 | 51.7 | 31.0 | 17.2 | 72.4 | 5.2 | 60.3 | 0.39 | -0.67 |
| ath_close_lowvol_accel_0to2 | 69 | 56.5 | 27.5 | 15.9 | 78.3 | 8.7 | 62.3 | 0.37 | -0.75 |
| ath_close_lowvol_accel_gt2 | 27 | 55.6 | 25.9 | 18.5 | 81.5 | 7.4 | 48.1 | -0.09 | -0.76 |

## Limitations

- Daily bars; no true premarket/Globex conditioning yet.
- Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.
- Historical base rates are not a forecast; they are the reference distribution.

## Machine payload

```json
{
  "bars": 1258,
  "context": {
    "median_5d_pct": -0.09,
    "median_mae5_pct": -0.76,
    "p_below_signal_low": 18.5,
    "p_gap_down": 7.4,
    "p_higher_high": 81.5,
    "p_up_5d": 48.1
  },
  "generated_at": "2026-09-21T22:14:15.343124+00:00",
  "instrument": "ES=F",
  "limitations": [
    "Daily bars; no true premarket/Globex conditioning yet.",
    "Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.",
    "Historical base rates are not a forecast; they are the reference distribution."
  ],
  "lookback": "5y",
  "matched_state": "ath_close_lowvol_accel_gt2",
  "model_version": "market-brief-base-rates-v1",
  "probabilities": {
    "continuation": 55.6,
    "failure": 18.5,
    "rotation": 25.9,
    "sum": 100.0
  },
  "safety": {
    "mode": "ANALYSIS_ONLY",
    "orders_enabled": false,
    "risk_config_touched": false
  },
  "span": [
    "2021-09-21",
    "2026-09-21"
  ],
  "states": {
    "__all__": {
      "label": "all_days",
      "median_5d": 0.37,
      "median_mae5": -1.23,
      "n": 1253,
      "p_continuation": 52.6,
      "p_failure": 33.4,
      "p_gap_down": 46.0,
      "p_higher_high": 55.4,
      "p_rotation": 14.0,
      "p_up_5d": 58.3,
      "raw": {
        "below_signal_low": 45.8
      }
    },
    "ath_close_hivol": {
      "label": "ath_close_hivol",
      "median_5d": 0.39,
      "median_mae5": -0.67,
      "n": 58,
      "p_continuation": 51.7,
      "p_failure": 17.2,
      "p_gap_down": 5.2,
      "p_higher_high": 72.4,
      "p_rotation": 31.0,
      "p_up_5d": 60.3,
      "raw": {
        "below_signal_low": 24.1
      }
    },
    "ath_close_lowvol_accel_0to2": {
      "label": "ath_close_lowvol_accel_0to2",
      "median_5d": 0.37,
      "median_mae5": -0.75,
      "n": 69,
      "p_continuation": 56.5,
      "p_failure": 15.9,
      "p_gap_down": 8.7,
      "p_higher_high": 78.3,
      "p_rotation": 27.5,
      "p_up_5d": 62.3,
      "raw": {
        "below_signal_low": 21.7
      }
    },
    "ath_close_lowvol_accel_gt2": {
      "label": "ath_close_lowvol_accel_gt2",
      "median_5d": -0.09,
      "median_mae5": -0.76,
      "n": 27,
      "p_continuation": 55.6,
      "p_failure": 18.5,
      "p_gap_down": 7.4,
      "p_higher_high": 81.5,
      "p_rotation": 25.9,
      "p_up_5d": 48.1,
      "raw": {
        "below_signal_low": 18.5
      }
    },
    "not_ath_close": {
      "label": "not_ath_close",
      "median_5d": 0.39,
      "median_mae5": -1.35,
      "n": 1099,
      "p_continuation": 52.3,
      "p_failure": 35.7,
      "p_gap_down": 51.5,
      "p_higher_high": 52.4,
      "p_rotation": 12.0,
      "p_up_5d": 58.1,
      "raw": {
        "below_signal_low": 49.1
      }
    }
  },
  "today": {
    "accel5_pct": 2.7,
    "close": 7830.75,
    "date": "2026-09-21",
    "is_ath_close": true,
    "low": 7829.0,
    "state": "ath_close_lowvol_accel_gt2",
    "vix": 14.869999885559082
  }
}
```
