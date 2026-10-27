# H1 score — 2026-10-26

**strategy_id:** `h1_sticky_oi_gamma_flip_es`
**Verdict:** `INSUFFICIENT`
**Kill rule hit:** rule 2, eligible estimation sessions `< 250`. Rule 1 did not fire.
**Mean:** not computed. Bootstrap interval: not computed.
**Estimation sessions admitted:** 0
**Held-out sessions:** 0
**Exclusion log:** empty. No session entered the sample, so FOMC, CPI, NFP, monthly expiration, and month-end tags were not applied.

This note records a data inventory. It does not reject or accept H0.

## What was on disk

Options chains live in `engine/data/options_signals/chain_snapshots/`, written by `engine/scripts/options_signals_snapshot.py`. That script reads a live CBOE delayed feed and states that a historical snapshot is not computable from it. Archive contents:

| Date | SPY files | QQQ files | Last SPY file | Captured (America/Chicago) | Raw timestamp inside the file |
|---|---:|---:|---|---|---|
| 2026-09-22 | 12 | 11 | `SPY_150504.json` | 2026-09-22 15:05:04 | 2026-09-22 20:04:42 |
| 2026-09-23 | 14 | 14 | `SPY_150505.json` | 2026-09-23 15:05:05 | 2026-09-23 03:54:59 |
| 2026-09-24 | 7 | 7 | `SPY_120612.json` | 2026-09-24 12:06:12 | 2026-09-23 03:54:59 |

No SPX chain is in the archive. Each SPY file examined has 12,380 contracts. The 2026-09-22 close file has 8,028 contracts with both gamma and open interest nonzero (`gamma_sum` 43.7379, `oi_sum` 17,691,354). The 2026-09-23 15:05 file and the 2026-09-24 12:06 file share the same raw timestamp, the same `gamma_sum` 44.0373, and the same `oi_sum` 17,691,354. The 2026-09-24 file is a repeat of the 2026-09-23 payload, captured after 09:35, so it cannot be the prior close for 2026-09-24 and it cannot be used for 2026-09-24 itself.

`data_delayed_minutes` is 15. Source string is `CBOE delayed quotes`. The 2026-09-22 15:05 capture is the only file whose raw timestamp matches the capture. It is the last stored print of that session, about fifteen minutes behind the cash close, and it is known before 09:35 on 2026-09-23. That is one candidate prior chain, not a close-settlement chain, and not a sample.

## Prices

`market_data_bars` in `engine/data/jarvis_trader.db`, read-only:

- ES `1m` contains `2026-09-23T14:35:00` and `2026-09-23T15:05:00`. Those are 09:35 and 10:05 America/Chicago on the one day a prior SPY chain exists. The 2026-09-24 stamps are absent.
- MES `1m` spans 2026-06-07 through 2026-10-06 overall, and contains 0 bars from 2026-09-22 through 2026-09-24.

Closes were not read. `compute_gex` was not called on these files. A one-day point change would be a look at the outcome after the sample had already failed the minimum.

## Why the count is zero

A row needs a prior completed session's chain and the next session's 09:35 and 10:05 ES prints. The archive can supply one prior chain (2026-09-22) for one decision day (2026-09-23). Two hundred fifty estimation sessions plus a sixty-session holdout are not in the store. Admitting the single candidate, or refusing it because the print is a delayed 15:05 capture rather than the official close, both leave the estimation count under 250. Rule 2 stops the record before a mean.

## Verification

- Calculator: `engine/tests/test_options_flow.py` — 7 passed in 1.56s on `engine/.venv` earlier on 2026-10-26. That checks the hand-computed one-contract case. It does not score H1.
- This run: chain dates, gamma/OI occupancy, raw timestamps, and the presence of two ES 1-minute stamps were read from the files above. Session rows were not rebuilt. H1 is not validated.

## Gap that would change this verdict

A point-in-time SPX chain, or a SPY chain with the ×10 scale stored on every row, with gamma and open interest as of each prior session close, covering at least 250 eligible estimation sessions after the registered exclusions, plus the last 60 eligible sessions held out. ES 1-minute prints at 09:35 and 10:05 America/Chicago have to cover those same decision days. The live CBOE snapshot task will not backfill that history.

The purchase named in `docs/plans/JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md` remains the only one this record allows: one historical OPRA pull on the existing Databento credit, or a chain already entitled. ThetaData Standard, Sierra Chart, Denali, CME depth, and the Unusual Whales API stay unauthorized. No order path, paper-config, or kill-switch change follows from this verdict.

## Re-run

There is no scoring command in the repo. After a chain store exists, the inventory that produced this note is a read of `engine/data/options_signals/chain_snapshots/` plus:

```text
SELECT ts_utc FROM market_data_bars
WHERE symbol = 'ES' AND interval = '1m'
  AND ts_utc IN ('2026-09-23T14:35:00', '2026-09-23T15:05:00');
```

A new scoring note is required before any mean is reported. This note's zero counts stay as the 2026-10-26 result.
