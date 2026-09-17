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

## 4. p_edge is carried by single-trade windows (CORRECTED 2026-09-17)

> **Correction.** The first version of this section reported "29 of the 32 profitable
> windows are single-trade" and "the multi-trade subset is 3/25 = 0.12". Both numbers were
> **wrong**: they were inferred from the sign/shape of `profit_factor` (`inf` was assumed to
> imply a single trade), and `inf` only means *no losing trades* — it can occur with several
> winners. The figures below are measured directly from per-window `oos_trades` via
> `_gate_v2_helpers.window_quality`, which is now recorded in the verdict JSON and printed
> by the runner. Old figures are retained here so the error is auditable.

Measured window structure (deep cache, 82 windows, 6-month train / 1-month step):

| trades in window | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| windows | 28 | **47** | 5 | 2 |

| quantity | value |
|---|---|
| windows with trades | 54 |
| **single-trade windows** | **47 of 54 (87 %)** |
| median trades per window | **1.0** |
| `p_edge` (as reported) | 0.5926 (32/54) |
| `p_edge` excluding single-trade windows | **0.7143** (5 of the 7 multi-trade windows) |
| `p_edge` at the gate-standard floor (≥ 5 trades) | **0.0000** — *zero* windows reach 5 trades |
| `sample_adequate_at_gate_floor` | **False** |

So the real shape of this evidence is not "a decent edge diluted by noise", and it is also
not the 0.12 first reported. It is: **a window set with almost no usable samples.** 87 % of
traded windows contain exactly one trade, the median window contains one trade, and *not one
window* reaches the five-trade floor the gate standard defines for a window to count
(`MIN_OOS_TRADES_PER_WINDOW = 5`). The 0.7143 over multi-trade windows is computed from
**7 windows** — far too few to carry a `p_edge` claim in either direction.

This matters for the gate: `p_edge` is a fraction of *windows*, so a strategy whose windows
mostly contain a single anonymous trade can move it almost arbitrarily. The companion
`window_quality` block exists so this is visible at verdict time instead of being inferred
after the fact from PF shapes.

Why the floor is 1 and not 5: 37 runners override the gate standard down to 1, with explicit
comments — SMA trend strategies fire only 1-3 trades per 2-month OOS window, so a 5-trade
floor returns `INSUFFICIENT_SAMPLE` everywhere. That trade-off is deliberate; what was
missing was any reporting of its consequence. Raising the floor is **not** the fix (it would
fail every trend strategy); reporting the elevation is.

## 5. Economics — modest, positive, and not promotion-grade

Fixed params over the whole deep sample, `risk_per_trade=1%`, `$50,000` initial:

| champion | PF | trades | trades/yr | CAGR | max DD | engine Sharpe | honest Sharpe |
|---|---|---|---|---|---|---|---|
| `block=[]` (window-selected champion) | 1.6952 | 122 | 16.696 | **+2.5361 %** | 4.4833 % | 0.874 | **0.225** |
| `block=["Crisis"]` (pre-registered) | 1.5581 | 112 | 15.327 | +1.8436 % | 4.5708 % | 0.7033 | 0.1734 |

Honest Sharpe applies the observed-trades-per-year correction:
`0.874 × sqrt(16.696/252) = 0.225`. Win rate 52.46 %, final equity $60,041.37.
CAGR is computed from the equity curve. Per §5a that curve **over-charges commission** (1.75×
the documented fee) and remains **too low**, while the trade-ledger metrics are cost-free and
**too high** — so read 2.5361 % as a lower bound and 2.9397 % (zero-cost) as an upper bound.

### 5a. Cost-ledger finding: the two bases disagree in OPPOSITE directions (CORRECTED 2026-09-17)

> **Correction.** The first version of this section explained the gap as
> "entry commission ($349.06) + entry spread ($1,407.50)". That was **wrong** — the leg split
> was inferred from code reading, not measured. A second attempt ("4 × commission") was right
> about the multiple but **wrong about the rate**: it multiplied by `config.py`'s
> `COMMISSION_PER_CONTRACT=1.42` while the runner actually executes at
> `commission_per_contract=0.62`, inflating the prediction 2.29×. The figures below are
> measured by instrumenting the cost hooks themselves
> (`engine/backtest/probe_cost_charge_by_callsite.py`) and the reconciliation closes to
> **$0.00 residual**.

Measured charge-by-charge decomposition of the full-sample `block=[]` run
(122 trades, Σcontracts = 563, runner commission rate = **$0.62/contract**, not the
configured $1.42):

| charged to `capital` | amount | n calls |
|---|---|---|
| commission — entry (`_process_pending_entry`) | $698.12 | 122 |
| commission — EOD close (`_check_eod_close`) | $256.68 | 59 |
| commission — stop exit (`_check_stop_exit`) | $141.36 | 22 |
| commission — target exits (`_check_targets_exit`) | $63.24 | 27 |
| commission — run-level exits | $236.84 | 41 |
| **commission subtotal** | **$1,396.24** | 271 (= 122 entries + 149 exit legs) |
| exit spread (`_exit_spread_cost`, all paths) | **$351.88** | 149 |
| **total** | **$1,748.12** | |
| ledger `sum(trade.pnl)` − equity change | $1,748.12 | |
| residual | **$0.00 (0.000 %)** | |

Every exit path charges commission — entry pays `2 × Σc × cpc` ($698.12) and the four exit
paths together pay the same again ($698.12) — so the 4× is uniform, not path-specific. That
was the one thing the earlier code-reading guess got right; the *rate* was the error.

So the reconciliation is exact, and the mechanism is:

- `_transaction_cost()` is **already** a round trip (`2 × contracts × cpc`, per its own
  docstring and PR #733), but it is charged **at entry** *and* **again at every exit leg** →
  `4 × Σcontracts × cpc` = 4.0000 × $349.06 = $1,396.24. Pinned by test.
- `trade.pnl` carries **no commission and no spread at all** — it is the raw price move.
  The entry-side half-spread does move the fill, but ATR-anchored stops/targets are
  recomputed from that fill, so it cancels in the realised price distance; the exit-side
  half-spread is an explicit `capital`-only deduction. Pinned by test.
- `spread_cost_total` reports **both** half-spreads even though only the exit side is
  realised on this path (measured $351.88 charged vs $703.75 reported).

**The two metric bases are wrong in opposite directions:**

| basis | what it includes | direction |
|---|---|---|
| `trade.pnl` → PF, win rate, `engine_sharpe`, `total_pnl` | **no commission, no spread** | **optimistic** |
| `final_capital` → CAGR, max drawdown | commission at **1.75×** the documented real fee | **pessimistic** |

Commission multiple against the *documented* fee in `config.py` ($1.42 round trip):
charged $1,396.24 vs correct $799.46 = **1.7465×**.

So the honest CAGR is bracketed, not known:

| basis | CAGR |
|---|---|
| `total_pnl`-derived (zero cost — upper bound) | 2.9397 % |
| equity curve (current, commission 1.7465×) — lower bound | **2.5361 %** |
| corrected cost model (linear estimate, ±0.16 pp) | ≈ **2.70 %** |

The corrected figure is an *estimate*: it moves the $596.78 overcharge linearly
(596.78 / 50,000 / 7.307y ≈ 0.163 pp/yr) and is not a re-run. **The direction of the finding
is what matters: gate PF/Sharpe are optimistic, gate CAGR/DD are pessimistic, and no single
number in the verdict is a correct net-of-cost economics figure.**

This remains **research-path evidence only**. Fixing the ledger changes every PF/Sharpe/CAGR
the gate has ever recorded, so it belongs in its own reviewed PR with the executable
contract already shipped here
(`tests/test_backtester_cost_ledger_consistency.py`, 5 pins + 2 strict-xfail targets).

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
