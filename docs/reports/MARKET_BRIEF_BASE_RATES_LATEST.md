# Market Brief — Measured Base Rates

Generated: 2026-09-22T03:36:39.012364+00:00  ·  model `market-brief-base-rates-v1`

## Safety

- `mode=ANALYSIS_ONLY` · `orders_enabled=false` · `risk_config_touched=false`
- No broker, order routing, risk config, kill-switch, .env or symbol-gate change.

## Today's state

- Date: `2026-09-22`  ·  ES close `7834.25`  ·  low `7829.00`
- New ATH close: `True`  ·  VIX `None`  ·  5d accel `3.23%`
- Matched state: `ath_close_hivol`  (n=58)

## Probability block (next session)

| Outcome | Probability |
|---|---:|
| Continuation (close higher) | **51.7%** |
| Rotation (down close, holds low) | **31.0%** |
| Failure (down close, breaks low) | **17.3%** |
| Sum | 100.0% |

## Context

| Metric | Value |
|---|---:|
| P(higher high next session) | 72.4% |
| P(gaps below today's open) | 5.2% |
| P(trades below today's low) | 24.1% |
| P(up 5 sessions) | 60.3% |
| Median 5-session return | 0.39% |
| Median 5-session adverse excursion | -0.67% |

## State table (causal, no lookahead)

| State | n | Cont. | Rot. | Fail. | P(higher high) | P(gap down) | P(up 5d) | med 5d | med MAE5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_days | 1254 | 52.6 | 14.0 | 33.4 | 55.3 | 46.1 | 58.3 | 0.37 | -1.23 |
| not_ath_close | 1100 | 52.3 | 12.0 | 35.7 | 52.4 | 51.5 | 58.2 | 0.39 | -1.35 |
| ath_close_hivol | 58 | 51.7 | 31.0 | 17.3 | 72.4 | 5.2 | 60.3 | 0.39 | -0.67 |
| ath_close_lowvol_accel_0to2 | 69 | 56.5 | 27.5 | 16.0 | 78.3 | 8.7 | 62.3 | 0.37 | -0.75 |
| ath_close_lowvol_accel_gt2 | 27 | 55.6 | 25.9 | 18.5 | 81.5 | 7.4 | 48.1 | -0.09 | -0.76 |

## Limitations

- Daily bars; no true premarket/Globex conditioning yet.
- Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.
- Historical base rates are not a forecast; they are the reference distribution.

## Machine payload

```json
{
  "bars": 1259,
  "context": {
    "median_5d_pct": 0.39,
    "median_mae5_pct": -0.67,
    "p_below_signal_low": 24.1,
    "p_gap_down": 5.2,
    "p_higher_high": 72.4,
    "p_up_5d": 60.3
  },
  "generated_at": "2026-09-22T03:36:39.012364+00:00",
  "instrument": "ES=F",
  "limitations": [
    "Daily bars; no true premarket/Globex conditioning yet.",
    "Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.",
    "Historical base rates are not a forecast; they are the reference distribution."
  ],
  "lookback": "5y",
  "matched_state": "ath_close_hivol",
  "model_version": "market-brief-base-rates-v1",
  "probabilities": {
    "continuation": 51.7,
    "failure": 17.3,
    "rotation": 31.0,
    "sum": 100.0
  },
  "safety": {
    "mode": "ANALYSIS_ONLY",
    "orders_enabled": false,
    "risk_config_touched": false
  },
  "span": [
    "2021-09-21",
    "2026-09-22"
  ],
  "states": {
    "__all__": {
      "label": "all_days",
      "median_5d": 0.37,
      "median_mae5": -1.23,
      "n": 1254,
      "p_continuation": 52.6,
      "p_failure": 33.4,
      "p_gap_down": 46.1,
      "p_higher_high": 55.3,
      "p_rotation": 14.0,
      "p_up_5d": 58.3,
      "raw": {
        "below_signal_low": 45.9
      }
    },
    "ath_close_hivol": {
      "label": "ath_close_hivol",
      "median_5d": 0.39,
      "median_mae5": -0.67,
      "n": 58,
      "p_continuation": 51.7,
      "p_failure": 17.3,
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
      "p_failure": 16.0,
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
      "n": 1100,
      "p_continuation": 52.3,
      "p_failure": 35.7,
      "p_gap_down": 51.5,
      "p_higher_high": 52.4,
      "p_rotation": 12.0,
      "p_up_5d": 58.2,
      "raw": {
        "below_signal_low": 49.2
      }
    }
  },
  "today": {
    "accel5_pct": 3.23,
    "close": 7834.25,
    "date": "2026-09-22",
    "is_ath_close": true,
    "low": 7829.0,
    "state": "ath_close_hivol",
    "vix": null
  }
}
```
