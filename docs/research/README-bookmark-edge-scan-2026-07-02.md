# X-Bookmark Trading-Edge Scan — 2026-07-02

Exhaustive scan of the newest 200 X.com bookmarks (2026-W27 + W26) for backtestable
trading edge. Pipeline: enrich embedded links/media → 20-way parallel analysis →
adversarial dedupe/verify/tier → gate-v2 validation of Tier-A survivors.

**Funnel:** 200 analyzed → 58 trading-relevant → 30 raw hypotheses → 19 survivors
(10 duplicates merged) → **2 Tier-A**.

## Artifacts in this PR
- `bookmark-edge-scan-2026-07-02.md` — full deep-dive (all survivors, tools, coverage appendix).
- `bookmark-edge-scan-2026-07-02.cards.jsonl` — 19 strategy cards (funnel-schema; feeds the robust funnel).
- `engine/backtest/generate_sma12_momentum_signals.py` + `run_spy_sma12_rank1.py` — Tier-A #1.
- `engine/backtest/generate_overnight_hold_signals.py` + `run_spy_overnight_rank1.py` — Tier-A #2.
- `engine/backtest/generate_supertrend_signals.py` + `run_spy_supertrend_weekly_rank1.py` — Tier-B (runnable, no new data feed).
- `engine/backtest/generate_atr_band_signals.py` + `run_spy_atr_band_rank1.py` — Tier-B polarity test (breakout **refuted**).
- `engine/data/gate_v2_verdicts/SPY_{sma12momentum,overnighthold,supertrendweekly,atrband}_rank1.json` — real gate-v2 output.

## Tier-A gate-v2 results (33yr SPY daily, 1993–2026)

Both edges are **real and reproduced**, and both currently read **FAIL** on gate-v2 —
but only on the `mc_95th_dd` drawdown criterion, which is calibrated for *intraday
futures* strategies, not long-biased equity-index strategies. 3 of 4 CORE criteria
pass for both (PF-CI-lower, p_edge, DSR). Reported honestly; **not** promoted.

| Strategy | CAGR | Sharpe | maxDD | Benchmark (buy&hold) | Gate v2 | Real edge |
|---|---|---|---|---|---|---|
| sma12_monthly_momentum | 10.1% | **0.95** | **-16.6%** | 10.8% / 0.77 / -50.8% | FAIL (dd 21.9%>6%) | ~half the drawdown at ~equal return |
| spy_overnight_hold | 10.0% | **0.95** | -32.8% | 10.8% / 0.64 / -55.2% | FAIL (dd 23.2%>6%) | overnight-only ≈ all of SPY's return; **intraday-only = 0.7% CAGR / 1.28x** |

The overnight split is the headline: over 33 years, holding SPY *only during RTH*
returned essentially nothing (Sharpe 0.12) — the entire risk premium accrued overnight.

## Tier-B trend results (33yr SPY, runnable without a new data feed)

Two of the eight Tier-B survivors are pure price/vol strategies that need no options or
GEX feed, so they were backtested through the same gate here rather than deferred.

| Strategy | Bars | CAGR | Sharpe | maxDD | Benchmark | Gate v2 | Verdict |
|---|---|---|---|---|---|---|---|
| supertrend_weekly_spx | weekly | 8.0% | **0.735** | **-27.2%** | 10.7% / 0.685 / -54.6% | FAIL (dd 28.5%>6%) | **Real** — beats buy&hold Sharpe, halves DD; 3/4 CORE, DD-only fail |
| atr_band_breakout | daily | 4.5% | 0.53 | -29.2% | 10.8% / 0.644 / -55.2% | FAIL (dd 27.4%, **dsr 0.0**) | **Refuted** — see below |

**`supertrend_weekly_spx`** is a genuine risk-reducer: a weekly Supertrend(ATR10, ×3)
long/cash filter *raises* Sharpe over buy&hold (0.735 vs 0.685) while cutting max drawdown
roughly in half (−27% vs −55%), at the cost of ~2.7pp CAGR (it sits in cash ~28% of the
time, missing some recovery). PF-CI-lower 1.22, p_edge 1.0, **DSR 0.9998** — passes every
CORE criterion except the intraday-futures DD ceiling. Same story as the two Tier-A edges.

**`atr_band_breakout` — the bookmark's hypothesis is refuted on SPY.** The scan flagged an
open question: does a close beyond an MA±k·ATR band *continue* (breakout) or *revert*? The
runner tests all four configs (ma20/k2.5/atr14):

| Config | Sharpe | CAGR | maxDD |
|---|---|---|---|
| breakout, long-only | 0.31 | 1.8% | -28.4% |
| breakout, long/short | **-0.21** | -3.6% | -77.9% |
| meanrev, long-only | 0.51 | 4.0% | -28.1% |
| meanrev, long/short | 0.53 | 4.5% | -29.2% |

Breakout *loses* on SPY; mean-reversion is the only positive polarity — but even the best
config underperforms buy&hold on Sharpe (0.53 < 0.644) and its **DSR collapses to 0.0** after
deflating for the 24 trials searched. This is a **genuine FAIL**, not a threshold artifact:
no promotable edge here. Kept in the PR as a documented negative result (the polarity finding
is itself useful — don't chase ATR-band breakouts on index ETFs).

## Equity-strategy-class DD threshold — analysis (NOT applied)

Four of the survivors are long-biased equity strategies whose *only* real gate blocker is
`mc_95th_dd` — a **6% ceiling calibrated for intraday futures**, where the underlying itself
never draws down 50%. SPY buy&hold's own `mc_95th_dd` is ~55%. Applying a futures-intraday
DD bar to a long-biased equity swing strategy is a category error.

| Strategy | mc_95th_dd | PF-CI | p_edge | DSR | Passes CORE at DD≤25% | at DD≤30% |
|---|---|---|---|---|---|---|
| sma12_monthly_momentum | 21.9% | 1.74 | 1.0 | 1.0 | **✓** | ✓ |
| spy_overnight_hold | 23.2% | 1.12 | 1.0 | 0.999 | **✓** | ✓ |
| supertrend_weekly_spx | 28.5% | 1.22 | 1.0 | 0.9998 | ✗ | **✓** |
| atr_band_breakout | 27.4% | 1.13 | 0.999 | **0.0** | ✗ (DSR) | ✗ (DSR) |

**Recommendation (advisory — implement only on Amo's Tier-3 call):** introduce a strategy-class
DD ceiling instead of one global constant. An `equity_swing` class at **DD ≤ 25%** would pass
`sma12_monthly_momentum` and `spy_overnight_hold` on CORE 4/4; a **≤ 30%** ceiling would add
`supertrend_weekly_spx`. `atr_band_breakout` would still fail on DSR at any DD ceiling — as it
should. This keeps the 6% bar for intraday-futures strategies untouched.

*Not applied here:* `_gate_v2_helpers.py` is a `[safety-review]`-adjacent constant governing
what can route to capital. Changing it is a deliberate risk decision, not an automated PR edit.
This section documents the numbers so the decision can be made with them in hand.

## Honest caveats
- Both Tier-A are **long-biased equity** strategies; the gate's 5–6% DD ceiling is a
  futures-intraday bar. Promotion would need a strategy-class-appropriate DD threshold
  or a vol-target/hedge overlay — a **Tier-3 (Amo) decision**, not automated here.
- `spy_overnight_hold` PnL is **gross** of the close/open spread + overnight financing,
  which erode a thin per-night edge; a live implementation must model those.
- Tier-B (dealer-gamma/GEX, VRP straddle, stat-arb) is real but gated on a data-feed
  decision (GEX feed / SPX options + delta-hedge sim) — none native to the ES engine.
- Tier-C is thin/discretionary — only under a shared global-trial counter + PBO/permutation.

## Reproduce
```
cd engine
python backtest/run_spy_sma12_rank1.py
python backtest/run_spy_overnight_rank1.py
python backtest/run_spy_supertrend_weekly_rank1.py
python backtest/run_spy_atr_band_rank1.py
```
(SPY daily is loaded from the gitignored cache via absolute path; override with `--data`.)

_Draft PR — research output. No paper/live routing is enabled; `PAPER_CONFIGS` untouched._
