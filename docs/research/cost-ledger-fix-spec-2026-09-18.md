# Cost-ledger fix — specification and the decision it depends on

Date: 2026-09-17/18. Status: **spec, not code.** Research-path only; no config, routing, risk or
kill-switch surface. The code change is deliberately deferred to a reviewed PR because it
re-baselines every PF/Sharpe/CAGR the gate has ever recorded.

Reproduces with: `engine/backtest/probe_cost_charge_by_callsite.py` and
`engine/tests/test_backtester_cost_ledger_consistency.py`.

## What is measured (not inferred)

From instrumenting the cost hooks on the MES full sample (122 trades, Σcontracts = 563, runner
commission rate 0.62):

| charged to `capital` | amount | n calls |
|---|---|---|
| commission — entry (`_process_pending_entry`) | $698.12 | 122 |
| commission — EOD / stop / target / run exits | $698.12 | 149 |
| **commission subtotal** | **$1,396.24** | 271 |
| exit spread (`_exit_spread_cost`, all paths) | $351.88 | 149 |
| **total** | **$1,748.12** | |
| ledger `sum(trade.pnl)` − equity change | $1,748.12 | |
| residual | **$0.00 (0.000 %)** | |

And from the pinned tests:

- `trade.pnl` = raw price move only: **no commission, no spread**.
- `_transaction_cost()` is `2 × contracts × cpc` — its own docstring calls it a round trip — and it
  is charged at entry **and** again at every exit leg, i.e. **4 × Σcontracts × cpc**.
- The entry-side half-spread moves the fill, but ATR-anchored stops/targets are recomputed from that
  fill, so it cancels in the realised distance; only the exit side is a realised cost.
- `spread_cost_total` reports both half-spreads while only the exit side is realised
  ($703.75 reported vs $351.88 charged).

Consequences, both directions:

| basis | includes | direction |
|---|---|---|
| `trade.pnl` → PF, win rate, `engine_sharpe`, `total_pnl` | nothing | **optimistic** |
| `final_capital` → CAGR, max drawdown | commission at **1.7465×** the documented fee | **pessimistic** |

CAGR bracket for the current candidate: 2.9397 % (zero-cost, upper) / 2.5361 % (current equity,
lower) / ≈2.70 % (linear estimate under a single-round-trip model — an estimate, not a re-run).

## The decision that blocks the code

`config.py:244` documents:

    COMMISSION_PER_CONTRACT: float = Field(
        1.42,
        description="MES/MNQ CME round-trip commission ($0.72 exchange + $0.70 clearing)",
    )

Two readings, 4× apart in model effect:

- **(A) 1.42 = round trip.** Then a closed trade should be charged `1.42 × contracts` once, and
  `_transaction_cost`'s `× 2` is itself a bug (added by PR #733 believing 0.62 was per-leg).
- **(B) 1.42 = per leg.** Then a round trip is `2.84 × contracts`, and the `× 2` is right but the
  double *charging* (entry + exit) is the bug.

These are not interchangeable — they differ by 2× on the correct total, and one of them means the
existing `× 2` must be removed rather than kept. **This needs a factual answer (broker fee schedule
or a real fill), not an assumption.** PR #733 already got this wrong once by reasoning from the
docstring, so reasoning again is not good enough.

## Proposed change (once the reading is settled)

1. `trade.pnl` becomes the net figure: `raw_price_move − (allocated entry+exit costs)` for the
   tranche, so `sum(trade.pnl) == final_capital − initial_capital` to the cent.
2. `capital` charges **one** round trip per **contract**, exactly once, at the exit that closes that
   contract — never at entry and again at exit.
3. `_exit_spread_cost` semantics confirmed as one realised crossing, and `spread_cost_total` made to
   agree with what was actually charged.
4. `tests/test_backtester_cost_ledger_consistency.py`: the two strict-`xfail` targets flip to real
   assertions, and the five "current behaviour" pins are **replaced** — they exist to document the
   bug, so they must die with it.

## Impact that must ship with the change

Every recorded verdict's PF, win rate, engine Sharpe, `total_pnl`, CAGR and drawdown moves. Before
that lands, the PR must carry a measured before/after table over the archive — at minimum for
`MES_trend_vix_pctile_rank1`, `MES_trend_rank11` and `MGC_trend_rank4` — so the re-baselining is a
documented decision rather than a side effect. Any verdict whose PASS flips must be listed.

## Why this is not in a research PR

- It changes the meaning of every metric the gate thresholds were calibrated against; a research PR
  must not silently re-baseline the gate.
- It interacts with the deflation finding (PR #872/#873): the MES candidate already fails the ALT
  floor under campaign deflation (`0.2642 < 0.30`). Fixing costs moves the numerator too, so the two
  changes should be sequenced, not stacked.
- Recommended sequence: settle the cpc reading → this fix with its impact table → then re-decide the
  ALT `p_edge`/DSR policy on numbers that are finally consistent.

## Limits

- The measured decomposition covers the MES full sample only; other runners share the same
  `Backtester`, so the mechanism generalises, but per-symbol magnitudes are not yet tabulated.
- The corrected-CAGR figure is a linear estimate, explicitly not a re-run.
- `_check_stop_exit`/EOD/run exit paths were all confirmed to charge commission; the per-path split
  is in the probe output.
