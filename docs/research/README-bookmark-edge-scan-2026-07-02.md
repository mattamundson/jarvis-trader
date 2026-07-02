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
- `engine/data/gate_v2_verdicts/SPY_sma12momentum_rank1.json`, `SPY_overnighthold_rank1.json` — real gate-v2 output.

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
```
(SPY daily is loaded from the gitignored cache via absolute path; override with `--data`.)

_Draft PR — research output. No paper/live routing is enabled; `PAPER_CONFIGS` untouched._
