# Walk-Forward Vol-Targeting Validation — MGC / MES Trend

Closes the in-sample lookahead in `vol_target_experiment.py` (which set a
single global `target_vol` over the whole sample). Here `target_vol` is
estimated on each 6-month train window and applied only to the
following disjoint 2-month out-of-sample window; OOS trades are
pooled. The in-sample row reproduces the experiment's (lookahead) figure so
the size of the inflation is visible.

## Results (fixed vs vol-targeted)

| Symbol | Basis | Trades | PF | Sharpe | MaxDD $ |
|--------|-------|--------|----|--------|---------|
| MGC | in-sample fixed | 54 | 1.803 | 1.077 | 1,373 |
| MGC | in-sample vol-target | 54 | 2.252 | 1.659 | 519 |
| MGC | **OOS fixed** | 40 | 1.993 | 1.238 | 1,373 |
| MGC | **OOS vol-target** | 40 | 2.750 | 1.924 | 559 |
| MES | in-sample fixed | 40 | 0.642 | -0.607 | 1,763 |
| MES | in-sample vol-target | 40 | 0.805 | -0.350 | 609 |
| MES | **OOS fixed** | 32 | 0.672 | -0.574 | 1,763 |
| MES | **OOS vol-target** | 32 | 0.753 | -0.469 | 499 |

## Per-symbol detail

**MGC** — `MGC_2024-04-26_2026-05-20_1h.csv` | 54 total trades | 10 OOS windows | global target_vol=13.32%  
  In-sample Sharpe uplift: +0.582 (lookahead baseline)  
  **OOS Sharpe uplift: +0.686 | OOS MaxDD delta: $-813**  
  Per-window: vol-target Sharpe beat fixed in 6/10 windows  
  Verdict: **ROBUST_OOS**

**MES** — `MES_2024-04-26_2026-06-17_1h.csv` | 40 total trades | 10 OOS windows | global target_vol=12.74%  
  In-sample Sharpe uplift: +0.257 (lookahead baseline)  
  **OOS Sharpe uplift: +0.105 | OOS MaxDD delta: $-1,264**  
  Per-window: vol-target Sharpe beat fixed in 0/10 windows  
  Verdict: **DAMPENS_DD**

## Verdict

Robust OOS risk-adjusted uplift (Sharpe up + MaxDD down + window majority): MGC.

Drawdown-dampening only (MaxDD down but no reliable Sharpe edge — de-risks a weak/negative base strategy): MES.

Interpretation: if the OOS Sharpe uplift is close to (or above) the in-sample
uplift, the vol_target_experiment finding was not a lookahead artifact and
supports a formal live-sizer decision (owner-gated, safety-review). A large gap
between in-sample and OOS uplift would indicate the global-target_vol figure was
inflated.

## Caveats

- **Sizing overlay only.** Vol-targeting reweights the per-trade PnL of the
  existing fixed-1-contract Backtester run; it does NOT change entry/exit signals
  and touches no `risk/` or Backtester code. It cannot manufacture edge — it only
  rescales an existing return stream.
- **MES row uses UNFILTERED trend** (`min_rv_annualized=0`), which is
  negative-expectancy on this 2yr sample. The live MES trend PASS uses the
  realized-vol filter (`MES_MIN_RV_ANNUALIZED=9.0`). MES here is therefore a
  control showing vol-targeting dampens losses without creating edge — NOT the
  live MES configuration.
- **MGC uses its champion params** (fast=50, slow=120, atr=2.0) — the figures
  apply directly to the live MGC trend edge.
- Next step is a formal gate-v2 study + a live-sizer wiring decision; both are
  owner-gated (safety-review). This module is offline measurement only.
