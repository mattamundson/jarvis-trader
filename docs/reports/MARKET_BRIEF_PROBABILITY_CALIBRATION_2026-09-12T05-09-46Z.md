# Market Brief Probability Calibration Discovery

Generated: 2026-09-12T05:09:46.074354+00:00
Model version: `market-brief-daily-calibration-discovery-v1`

## Verdict

Dataset is large enough for a first reliability/base-rate read, but still daily-proxy only.

## Safety

- `mode=ANALYSIS_ONLY`
- `orders_enabled=false`
- `risk_config_touched=false`
- No engine/risk/kill-switch/env/broker/symbol-gate state was changed.

## Dataset

- Rows: `617`
- Date span: `2024-03-27` → `2026-09-11`
- Dataset CSV: `engine/data/market_brief_calibration/market_brief_calibration_rows_2026-09-12T05-09-46Z.csv`
- Source counts: `{'SPY': 618, 'QQQ': 618, '^VIX': 620, 'ES=F': 620, 'NQ=F': 620, 'MES=F': 620}`

## Label base rates

| Outcome | Count | Rate |
|---|---:|---:|
| continuation | 187 | 30.31% |
| rotation | 321 | 52.03% |
| failure | 109 | 17.67% |

## Regime counts

| Regime | Count | Rate |
|---|---:|---:|
| risk_off | 135 | 21.88% |
| risk_on | 185 | 29.98% |
| balanced | 297 | 48.14% |

## Brier score — lower is better

| Class | Brier |
|---|---:|
| continuation | 0.150763 |
| rotation | 0.207818 |
| failure | 0.14739 |
| macro_avg | 0.168657 |

## Reliability bins

```json
{
  "continuation": [
    {
      "bin": 1,
      "n": 0,
      "range": [
        0.0,
        0.2
      ]
    },
    {
      "avg_predicted": 0.2514,
      "bin": 2,
      "n": 300,
      "observed_rate": 0.0067,
      "range": [
        0.2,
        0.4
      ]
    },
    {
      "avg_predicted": 0.4963,
      "bin": 3,
      "n": 234,
      "observed_rate": 0.5385,
      "range": [
        0.4,
        0.6
      ]
    },
    {
      "avg_predicted": 0.6594,
      "bin": 4,
      "n": 83,
      "observed_rate": 0.7108,
      "range": [
        0.6,
        0.8
      ]
    },
    {
      "bin": 5,
      "n": 0,
      "range": [
        0.8,
        1.0
      ]
    }
  ],
  "failure": [
    {
      "avg_predicted": 0.1672,
      "bin": 1,
      "n": 209,
      "observed_rate": 0.177,
      "range": [
        0.0,
        0.2
      ]
    },
    {
      "avg_predicted": 0.2048,
      "bin": 2,
      "n": 408,
      "observed_rate": 0.1765,
      "range": [
        0.2,
        0.4
      ]
    },
    {
      "bin": 3,
      "n": 0,
      "range": [
        0.4,
        0.6
      ]
    },
    {
      "bin": 4,
      "n": 0,
      "range": [
        0.6,
        0.8
      ]
    },
    {
      "bin": 5,
      "n": 0,
      "range": [
        0.8,
        1.0
      ]
    }
  ],
  "rotation": [
    {
      "avg_predicted": 0.1753,
      "bin": 1,
      "n": 45,
      "observed_rate": 0.1333,
      "range": [
        0.0,
        0.2
      ]
    },
    {
      "avg_predicted": 0.291,
      "bin": 2,
      "n": 267,
      "observed_rate": 0.2996,
      "range": [
        0.2,
        0.4
      ]
    },
    {
      "avg_predicted": 0.5463,
      "bin": 3,
      "n": 305,
      "observed_rate": 0.7705,
      "range": [
        0.4,
        0.6
      ]
    },
    {
      "bin": 4,
      "n": 0,
      "range": [
        0.6,
        0.8
      ]
    },
    {
      "bin": 5,
      "n": 0,
      "range": [
        0.8,
        1.0
      ]
    }
  ]
}
```

## Limitations / next gates

1. Replace daily proxy with true premarket/Globex snapshots when second intraday feed is implemented.
2. Add macro calendar event-count/name features once parser preserves names.
3. Do not fit isotonic/logistic calibration until the sample count and class balance are sufficient.
4. Keep dashboard label as heuristic until calibrated coefficients pass reliability checks.

## Machine payload

```json
{
  "brier_score": {
    "continuation": 0.150763,
    "failure": 0.14739,
    "macro_avg": 0.168657,
    "rotation": 0.207818
  },
  "dataset_path": "engine/data/market_brief_calibration/market_brief_calibration_rows_2026-09-12T05-09-46Z.csv",
  "date_end": "2026-09-11",
  "date_start": "2024-03-27",
  "label_counts": {
    "continuation": 187,
    "failure": 109,
    "rotation": 321
  },
  "limitations": [
    "Daily bars are a proxy; this is not true premarket/Globex calibration.",
    "Macro-event names/counts are not included in v1 discovery rows.",
    "No live trading, risk config, kill switch, or broker state is touched.",
    "Use this to judge feasibility/base rates before fitting any calibration layer."
  ],
  "model_version": "market-brief-daily-calibration-discovery-v1",
  "regime_counts": {
    "balanced": 297,
    "risk_off": 135,
    "risk_on": 185
  },
  "reliability": {
    "continuation": [
      {
        "bin": 1,
        "n": 0,
        "range": [
          0.0,
          0.2
        ]
      },
      {
        "avg_predicted": 0.2514,
        "bin": 2,
        "n": 300,
        "observed_rate": 0.0067,
        "range": [
          0.2,
          0.4
        ]
      },
      {
        "avg_predicted": 0.4963,
        "bin": 3,
        "n": 234,
        "observed_rate": 0.5385,
        "range": [
          0.4,
          0.6
        ]
      },
      {
        "avg_predicted": 0.6594,
        "bin": 4,
        "n": 83,
        "observed_rate": 0.7108,
        "range": [
          0.6,
          0.8
        ]
      },
      {
        "bin": 5,
        "n": 0,
        "range": [
          0.8,
          1.0
        ]
      }
    ],
    "failure": [
      {
        "avg_predicted": 0.1672,
        "bin": 1,
        "n": 209,
        "observed_rate": 0.177,
        "range": [
          0.0,
          0.2
        ]
      },
      {
        "avg_predicted": 0.2048,
        "bin": 2,
        "n": 408,
        "observed_rate": 0.1765,
        "range": [
          0.2,
          0.4
        ]
      },
      {
        "bin": 3,
        "n": 0,
        "range": [
          0.4,
          0.6
        ]
      },
      {
        "bin": 4,
        "n": 0,
        "range": [
          0.6,
          0.8
        ]
      },
      {
        "bin": 5,
        "n": 0,
        "range": [
          0.8,
          1.0
        ]
      }
    ],
    "rotation": [
      {
        "avg_predicted": 0.1753,
        "bin": 1,
        "n": 45,
        "observed_rate": 0.1333,
        "range": [
          0.0,
          0.2
        ]
      },
      {
        "avg_predicted": 0.291,
        "bin": 2,
        "n": 267,
        "observed_rate": 0.2996,
        "range": [
          0.2,
          0.4
        ]
      },
      {
        "avg_predicted": 0.5463,
        "bin": 3,
        "n": 305,
        "observed_rate": 0.7705,
        "range": [
          0.4,
          0.6
        ]
      },
      {
        "bin": 4,
        "n": 0,
        "range": [
          0.6,
          0.8
        ]
      },
      {
        "bin": 5,
        "n": 0,
        "range": [
          0.8,
          1.0
        ]
      }
    ]
  },
  "safety": {
    "mode": "ANALYSIS_ONLY",
    "orders_enabled": false,
    "risk_config_touched": false
  },
  "sample_count": 617,
  "source_counts": {
    "ES=F": 620,
    "MES=F": 620,
    "NQ=F": 620,
    "QQQ": 618,
    "SPY": 618,
    "^VIX": 620
  }
}
```
