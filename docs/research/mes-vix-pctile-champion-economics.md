# MES VIX-percentile champion — economics and DSR trial-count sensitivity

Date: 2026-09-17
Author: unattended strategy-validation loop (`Jarvis-Strategy-Validation-Loop`)
Candidate: `MES_sma_trend_vix_pctile_blockCrisis_v1`
Verdict under audit: `engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json` (2026-09-17T21:47:39Z)
Analysis script: `engine/backtest/analyze_mes_vix_pctile_economics.py`
Raw output: `docs/research/mes-vix-pctile-champion-economics.json`

Scope: research evidence only. No live/paper routing, risk limit, kill-switch, broker
routing, `.env`, active-instrument gate, or order behaviour change. MES remains not
approved; MCL/MNQ/MGC remain halted.

## 1. Why this analysis exists

The recorded verdict reports **PASS via alt** with `p_edge=0.5926`, `dsr=0.9752`,
champion `blocked_tiers=[]`. Gate v2 records PF / DD / Sharpe **per window** and no
CAGR, and its DSR is deflated for the *runner's own grid size* (`n_grid_combos=4`).
Two questions therefore remain open, and this analysis answers both:

1. Is the champion **economically** meaningful, or is PF/Sharpe hiding triviality?
2. Does `dsr=0.9752` survive deflation at the **true campaign trial count**?

## 2. Data and parity discipline

Cache: `MES_2019-05-05_2026-08-26_1h.csv` — 43,010 bars,
2019-05-05T22:00Z → 2026-08-26T20:00Z (7.307y), 0 NaN and 0 duplicate timestamps,
sha256 `e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe`.
VIX: yfinance `^VIX` daily (live fetch, not stubbed).

The script **replays the runner's walk-forward loop** and refuses to report unless it
reproduces the archived verdict's own numbers:

| check | replay | archived verdict | match |
|---|---|---|---|
| `p_edge` | 0.5926 | 0.5926 | yes |
| total OOS trades | 63 | 63 | yes |
| `dsr` at `n_grid_combos=4` | 0.9770 | 0.9752 | yes (Δ 0.0018; 2,000 vs 10,000 permutations) |

Parity holds, so the downstream numbers below are comparable to the verdict.

## 3. DSR collapses with the real trial count

`trade_level_dsr` is the empirical (sign-permutation) DSR from PR #594, calibrated to
the actual payoff shape. It is still deflated by the `n_grid_combos` it is handed —
here the runner's 4-combo tier grid, not the number of hypotheses actually searched
against this deep cache.

| `n_trials` | DSR | ALT floor (0.30) |
|---|---|---|
| 4 (runner's own grid) | 0.9770 | pass |
| 9 | 0.9475 | pass |
| 25 | 0.8515 | pass |
| 50 | 0.7315 | pass |
| 100 | 0.5335 | pass |
| **200** | **0.2885** | **FAIL** |
| **500** | **0.0505** | **FAIL** |

The MES campaign against this deep cache is in the **hundreds** of trials (the rank1–rank11
trend campaign alone, plus the VIX-range family, the percentile family, MTF, ADX, RV-filter
and meta-label variants). At 200 trials the candidate is **below the ALT DSR floor**, and
at 500 it is indistinguishable from noise. The recorded `dsr=0.9752` is therefore an
**artifact of the runner's grid size**, not evidence of skill.

## 4. p_edge is inflated by degenerate single-trade windows

Of 82 windows, 54 produced at least one trade and 32 of those had PF > 1.0 → `p_edge = 32/54 = 0.5926`.
But **29 of those 32 profitable windows contain a single trade** (PF = `inf`).

| subset | profitable / total | p_edge |
|---|---|---|
| all windows with trades | 32 / 54 | 0.5926 (the reported number) |
| windows with a finite PF | 3 / 25 | **0.1200** |

So 91% of the windows counted as "profitable" are single-trade windows. The reported
`p_edge` is carried by windows that cannot distinguish edge from a coin flip, and the
multi-trade subset is 0.12. This is a **metric-fragility finding** for the gate itself:
`p_edge` treats `inf` (one winning trade) as a strong positive.

## 5. Economics — modest, positive, and not promotion-grade

Fixed params over the whole deep sample, `risk_per_trade=1%`, `$50,000` initial:

| champion | PF | trades | trades/yr | CAGR | max DD | engine Sharpe | honest Sharpe |
|---|---|---|---|---|---|---|---|
| `block=[]` (window-selected champion) | 1.6952 | 122 | 16.696 | **+2.5361 %** | 4.4833 % | 0.874 | **0.225** |
| `block=["Crisis"]` (pre-registered) | 1.5581 | 112 | 15.327 | +1.8436 % | 4.5708 % | 0.7033 | 0.1734 |

Honest Sharpe applies the observed-trades-per-year correction:
`0.874 × sqrt(16.696/252) = 0.225`. Win rate 52.46 %, final equity $60,041.37
(CAGR is computed from the equity curve, which is the cost-inclusive number).

### 5a. Metric-consistency finding: PF/Sharpe/total_pnl are gross of entry costs

`final_capital` and `sum(trade.pnl)` **do not reconcile**, and the gap is exactly the
entry-side cost the trade ledger never sees:

| quantity | value |
|---|---|
| `final_capital − initial_capital` | $10,041.37 |
| `total_pnl` (= `sum(trade.pnl)`) | $11,789.49 |
| **gap** | **$1,748.12** |
| entry commission (`122 trades × 4.615 avg contracts × $0.62`) | $349.06 |
| entry spread (`contracts × 2 ticks × $0.25 × 5`) | $1,407.50 |
| **entry costs total** | **$1,756.56** (100.5 % of the gap) |

`backtester.py` deducts entry commission and entry spread from `capital` at entry, while
`trade.pnl` (net of the exit-side half-spread only) is what feeds `gross_profit`,
`gross_loss`, `total_pnl`, PF, and the Sharpe return series. Consequence: **gate
PF/Sharpe are mildly optimistic** — they omit the entry-side half of round-trip cost.

CAGR impact, same run:

| basis | CAGR |
|---|---|
| equity curve (cost-inclusive, used above) | **2.5361 %** |
| `(initial + total_pnl) / initial` (entry costs omitted) | 2.9397 % |

So quoting CAGR from `total_pnl` would overstate the edge by **0.40 pp/yr (~16 % relative)**.
This is a research-path defect worth fixing, but it is **not** the kind of change this
loop should make unilaterally: it changes every PF/Sharpe the gate has ever recorded, so
it belongs in its own reviewed PR. Recorded here as an open item.

Reading of this:

- The trend edge is **real but modest**: +2.54 %/yr with a 4.48 % max drawdown over 7.31y,
  honest Sharpe 0.225. For scale, the previously certified live champion
  SMA(50,200)+2×ATR is −0.26 % CAGR at fixed params, so this is better — but 0.225 honest
  Sharpe is far from an institutionally meaningful edge and well under the "no MES config
  has ever had a true Sharpe > 1" ceiling already recorded in the rules.
- The **pre-registered Crisis block makes every metric worse** (CAGR −0.69 pp, PF −0.14,
  honest Sharpe −0.05, DD slightly worse). The hypothesis that an adaptive percentile
  Crisis gate preserves or improves the trend edge is **falsified on this sample**.
- Cost survival is unchanged from the family pattern: pessimistic yes, catastrophic no.

## 6. Conclusion

The candidate's ALT PASS does **not** survive honest multiple-testing deflation, and its
`p_edge` is dominated by single-trade windows. Its underlying SMA(60,200) trend shows a
modest positive edge, but the *adaptive VIX percentile gate that the candidate was
registered to test adds nothing and in fact detracts*. Consistent with that, the
in-sample window selection chose the **no-gate baseline** as champion.

Accordingly: **not promoted**, `candidate_registry.json` frozen params unchanged, no new
candidate id registered, and the queue item stays `ready_to_backtest`/paused rather than
advancing to forward testing.

## 7. Family-wide tz hardening shipped with this analysis

While auditing the fix that unblocked this run, **four further mixed-tz call sites** were
found that perform their own daily→intraday reindex (so they never went through the shared
helper) and would have failed identically on a tz-aware cache:

- `backtest/composite_strategies.py` — `_vix_series_and_tiers` and the daily-composite VIX path
- `backtest/run_spy_qqq_options_vertical.py` — VIX ffill onto the signal index
- `backtest/run_mgc_trend_mtf_rank1.py` — daily-regime date mapping

All now route through `trend_signals._daily_date_index`. A standing probe,
`tests/test_vix_tz_family_probe.py`, locks the class of failure: a static invariant that no
`backtest/*.py` may feed a bare `reindex(... .normalize())` target, positive assertions that
each family reindexer uses the shared helper, a live call of a family call site with a
tz-aware bar index, and an integration probe against the real deep cache.

`backtest/run_trend_vix_pctile_gate.py` (MCL/MNQ, halted `DO_NOT_TRADE_SYMBOLS`) was
deliberately **not** touched — research on halted instruments is out of scope for this loop.

## 8. Next bounded evidence steps

1. **Entry-cost consistency (new).** Make `trade.pnl` cost-inclusive on both legs, or
   document that PF/Sharpe are gross of entry costs. Every gate threshold calibrated on
   the current definition would shift; needs its own reviewed PR.
2. **Campaign-level DSR as standing practice.** Re-deflate for the true MES-campaign trial
   count rather than the runner's grid size, otherwise every ALT PASS from a small grid
   overstates skill.
3. **`p_edge` definition.** Decide whether `inf`/single-trade windows count as profitable
   (currently yes; 29 of the 32 "profitable" windows here are single-trade, and the
   multi-trade subset is 0.12).
4. Only then consider a **new** candidate: the honest no-gate trend baseline
   (SMA 60/200 + 2×ATR) on the deep cache, evaluated with campaign-level deflation rather
   than a 4-combo grid.
