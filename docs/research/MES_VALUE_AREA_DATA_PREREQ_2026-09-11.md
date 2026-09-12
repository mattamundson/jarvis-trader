# MES Value-Area Data Prerequisite Check — 2026-09-11

Scope: research-only prerequisite for VAH/VAL/POC value-area variants. No engine/risk/routing changes.

## Source file actually available locally

`engine/backtest/cache/MES_2024-04-26_2026-09-10_1h.csv`

Memory referenced a 2019→2026 deep cache, but the local cache discovery did **not** find that file. The current local candidate is the 2024-04-26→2026-09-10 1h cache.

## Verified shape

| Metric | Value |
|---|---:|
| Rows | 13,734 |
| Columns | timestamp, open, high, low, close, volume |
| Timestamp format | timezone-aware UTC (`+00:00`) |
| UTC span | 2024-04-26 05:00 → 2026-09-10 20:00 |
| CT span | 2024-04-26 00:00 → 2026-09-10 15:00 |
| Total CT calendar/session days | 740 |
| CT days with ≥1 RTH-like bar | 604 |
| CT days with ≥6 RTH-like bars | 585 |

## Verdict

**PASS for prerequisite / PARTIAL for strategy validation.**

- PASS: RTH session tagging is reconstructable from timezone-aware UTC timestamps using `America/Chicago`. A VAH/VAL/POC generator can safely group by CT date and split RTH vs overnight/session structure.
- PARTIAL: This is not the older 7.27y deep cache. It is a 2.38y cache; enough to prototype the feature extractor and run a preliminary VA hypothesis screen, but not enough to certify edge.

## Recommended implementation guardrails

1. Add a pure feature extractor first: `compute_rth_value_area(df, tz='America/Chicago', value_area_pct=0.70)`.
2. Require explicit timezone conversion; fail if timestamps are naive.
3. Treat 1h OHLCV value area as an approximation because true volume-at-price needs tick/price-bin data.
4. For strategy validation, require fresh/deep cache acquisition or restore the 2019→2026 cache before making edge claims.
5. Keep all MES routing unchanged; this is research-only.
