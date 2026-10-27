# H1 data contract — 2026-10-27

**strategy_id:** `h1_sticky_oi_gamma_flip_es`
**Verdict still in force:** `INSUFFICIENT`
**This note does not score H1.** No 09:35-to-10:05 return was computed. The position rule, horizon, 0.50-point cost, event exclusions, 250-session minimum, and 60-session holdout in `H1_sticky_oi_gamma_flip_es.md` are unchanged.

Companion to `H1_sticky_oi_gamma_flip_es_score_2026-10-26.md`. Nothing was downloaded. No order was sent. `engine/.env` was not edited. The Databento key was not printed and was not sent to Databento for this note.

## Local prices

One-minute bars in `engine/data/jarvis_trader.db` `market_data_bars`. A session counts only when both the 09:35 and 10:05 America/Chicago prints exist. Daylight-saving offsets were applied. Opens, highs, lows, and closes were not read.

| Symbol | Sessions | First | Last |
|---|---:|---|---|
| ES | 8 | 2026-09-18 | 2026-10-26 |
| MES | 27 | 2026-06-08 | 2026-08-17 |

The two windows do not overlap. Combined calendar: 35 dates. H1 needs 250 eligible estimation sessions plus 60 held out, after the registered exclusions. Local clocks are short of that. Estimation sessions admitted remain 0.

## What the options loader actually returns

`engine/backtest/databento_loader.py` `fetch_option_chains`:

- Dataset code written in source: `OPRA.PILLAR`
- Parent symbol: `{ROOT}.OPT` with `stype_in="parent"`
- Default schema: `ohlcv-1d`
- Joined schema: `definition`, on `instrument_id`, for strike, expiration, and call/put (`instrument_class`)

Columns the loader keeps: `timestamp`, `instrument_id`, `raw_symbol`, `expiration`, `strike_price`, `instrument_class`, `open`, `high`, `low`, `close`, `volume`, plus `underlying` on the definition frame.

**Missing for `compute_gex`:** `gamma` and `open_interest`. A daily option bar cannot feed `compute_gex`. Without both of those fields the function returns no flip.

The source marks `OPRA.PILLAR` and `{ROOT}.OPT` UNVERIFIED against a live response. `engine/tests/test_databento_opra.py` never calls the network. `DATABENTO_API_KEY` is present as one non-placeholder assignment, and `import databento` succeeds in `engine/.venv`. That is a local classification. It is not an authentication check and not a column check.

## Schemas the repo does not name

The repo mentions schema `statistics` for CME futures open interest, in the futures pilot, not on `OPRA.PILLAR`.

The repo is silent on an OPRA open-interest schema. The repo is silent on an OPRA quote schema. This note does not assign `statistics`, `mbp-1`, or `trades` to OPRA. Those names appear on the CME `GLBX.MDP3` path.

## Gamma builder

Not authorized in this pass. If a later document builds gamma, it has to call `bs_gamma` in `engine/backtest/run_spy_options_baseline.py`, use only the prior session, and be registered before any ES return is read. That document does not exist. Approval to write it is not implied here.

## The other session's ES file

A separate session has a Databento metadata quote of $20.72 for `GLBX.MDP3` `ohlcv-1m` on `ES.c.0`. That quote was not repeated and that file was not requested here. If that download is later approved, it can supply the price side of this record. It cannot supply gamma or open interest. Approval of that file is not approval to score this H1.

## Stop line

`INSUFFICIENT` remains the verdict. No estimation row can be admitted from the loader output above.

## Clock convention, frozen before any price is read.

A later scorer, when a file exists, uses the open of the 1-minute bar whose America/Chicago timestamp is exactly 09:35, and the open of the bar stamped exactly 10:05. The close of those bars is one minute later and is not the decision price. This paragraph does not authorize reading those opens now.
