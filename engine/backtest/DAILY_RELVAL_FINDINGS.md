# Daily ETF relative-value screen — findings (2026-06-26)

Standalone screener (`daily_relval_discovery.py`) over the deep free daily ETF caches —
the **deep-data complement** to the futures relative-value track. The futures RV track
found two survivors (ZB-ZN, M6E-M6B) but on a THIN basis: the IB free-data ceiling leaves
those legs with only ~1yr of 1h bars. Cash ETFs carry decades of free daily history, so an
ETF pairs screen is both (a) properly powered and (b) frequency/window-compatible with the
calendar sleeves — which would have made a genuine cross-family book buildable **had a
survivor existed**.

**11 economically-motivated pairs**, each a parameter-FREE z-reversion strategy (one
pre-registered config — W60, 2σ entry / 0.5σ exit / 6σ stop, 1bp/leg — no per-pair tuning,
so the only multiple-testing penalty is the 11 pairs, exactly like the calendar screener's
per-effect penalty). Graded on the SAME honest bar via the shared `daily_calendar_discovery`
grader: bootstrap PF-CI, p_edge, deflated Sharpe penalized for 11 trials, max-DD,
chronological H1/H2 stationarity, canonical gate-v2.

## Headline: a clean, well-powered NULL — 0 survivors, 0 gate-PASSes

| pair | n | PF-CI | p_edge | dsr(×11) | Sharpe | DD% | H1/H2 | gate |
|---|---|---|---|---|---|---|---|---|
| XLU_TLT | 2379 | 1.86 | 0.67 | 0.00 | 0.55 | 42.9 | 1.17/1.07 | FAIL |
| DIA_SPY | 3418 | 1.74 | 0.58 | 0.00 | 0.12 | 15.5 | 1.02/1.03 | FAIL |
| SPY_IWM | 2890 | 1.60 | 0.58 | 0.00 | 0.23 | 34.2 | 1.09/0.99 | FAIL |
| TLT_LQD | 2840 | 1.60 | 0.56 | 0.00 | −0.11 | 41.8 | 1.00/0.96 | FAIL |
| EEM_EFA | 2481 | 1.60 | 0.58 | 0.00 | 0.38 | 23.5 | 1.03/1.12 | FAIL |
| LQD_HYG | 2030 | 1.59 | 0.59 | 0.00 | 0.45 | 20.4 | 1.19/0.97 | FAIL |
| SPY_EFA | 2989 | 1.59 | 0.58 | 0.00 | 0.06 | 33.1 | 1.09/0.93 | FAIL |
| HYG_SPY | 2113 | 1.56 | 0.55 | 0.00 | 0.31 | 22.3 | 1.10/1.03 | FAIL |
| GLD_SLV | 2287 | 1.52 | 0.52 | 0.00 | −0.27 | 78.8 | 0.94/0.95 | FAIL |
| GLD_TLT | 2627 | 1.49 | 0.56 | 0.00 | −0.04 | 48.9 | 1.00/0.98 | FAIL |
| SPY_QQQ | 3337 | 1.45 | 0.52 | 0.00 | −0.33 | 65.1 | 0.90/1.00 | FAIL |

**Every pair fails, and the deflated Sharpe collapses to 0.000 across the board.** The
spreads DO revert gross — every PF-CI lower bound is > 1.4 — but the edge is too weak net
of cost (raw Sharpe −0.33 to +0.55) to survive the 11-trial deflation, and the drawdowns
are large. This is the documented reality: liquid-ETF pairs trading was an edge in the
early 2000s and has been **arbitraged away**. The screen surfaces it as dead, rigorously.

## Why each big drawdown happened — the pairs-trading failure mode

The worst drawdowns are the pairs most prone to **regime re-rating** (one leg structurally
outperforms for years, so the spread doesn't revert — it trends):
- **GLD_SLV 78.8%** — the 2011 silver spike-and-collapse; the gold/silver ratio re-rated, didn't revert.
- **SPY_QQQ 65.1%** — the multi-year tech-vs-broad divergence (2020-2023); growth re-rated.
- **GLD_TLT 48.9% / XLU_TLT 42.9% / TLT_LQD 41.8%** — duration regime shifts (the 2022 rate shock) blew out every spread with a Treasury leg.

These are the canonical reason naive z-reversion on cash pairs fails: the spread's mean is
not stationary across regimes, so a "2σ rich" reading is often the *start* of a re-rating,
not a reversion. p_edge ~0.5-0.6 (only ~half the monthly windows profitable) confirms the
signal is noise-dominated.

## Honest reads / caveats

- **Parameter-free is the point.** A pair that only works at one magic (window, entry-z)
  is overfit (Phase-3 "works only at one magic value → kill"). Searching params to surface
  a "winner" is the exact multiple-testing sin the campaign forbids; the pre-registered
  single-config NULL is the honest result. A vol/DV01-hedged spread variant is a possible
  follow-up but, given dsr=0 across all 11, is very unlikely to flip any to a gate-PASS —
  not pursued (avoids the "tweak until something passes" trap).
- **DD is over in-position-day returns** (the active series, matching the calendar grader's
  held-day convention); a full-equity-curve DD with flat days would be milder, but the
  binding failures are dsr=0 + weak Sharpe, not DD alone.

## What this closes

Relative value is **null at both levels** tested: thin-futures (2 survivors but ~1yr basis,
forward-shadowed and unconfirmed) and deep-ETF (0 survivors, decades of data). The
campaign's durable, gate-clearing edges are concentrated in the **calendar/seasonal class**
(`DAILY_CALENDAR_FINDINGS.md` — 10 gate-PASSes), where the driver is structural flow
(holiday/turn-of-month/year-end/pre-FOMC positioning) rather than an arbitrageable
mispricing. There is **no deep-data RV sleeve to diversify the calendar book with** — the
cross-family combination is moot, which is itself the honest answer.
