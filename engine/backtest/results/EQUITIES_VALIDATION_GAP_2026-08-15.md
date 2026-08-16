# Equities validation-gap fill — QQQ, AAPL, TSLA (2026-08-15)

## What this is

`engine/CLAUDE.md` "Active Instruments > Equities" documents that QQQ, AAPL, and TSLA
trade real paper capital through the options/equities scanner with **zero backtest
validation artifacts on file** — no `wfe_snapshots` row, no `engine/backtest/results/`
file, no `run_<symbol>_*.py` script. SPY has four such scripts (`run_spy_sma12_rank1.py`,
`run_spy_atr_band_rank1.py`, `run_spy_overnight_rank1.py`,
`run_spy_supertrend_weekly_rank1.py`, all added 2026-07-02 per `git log`) but its own
gate-v2/WFE record is REJECTED.

This PR runs the same gate-v2 pipeline SPY's scripts use against QQQ, AAPL, and TSLA and
records the result. **It produces data for a human decision. It does not change
`DO_NOT_TRADE_SYMBOLS`, `PAPER_CONFIGS`, `OPTIONS_WATCHLIST`, or any routing/config —
all four names keep trading as-is per Amo's explicit 2026-08-03 decision recorded in
`engine/CLAUDE.md`.** Nothing here overrides that decision; it only replaces "no
verdict exists" with "here is a real verdict."

**Doc-staleness side note (not fixed here, out of scope):** both `engine/CLAUDE.md` and
this task's own framing describe the 4 SPY scripts as "pre-2026-04-02." `git log
--follow` on `run_spy_sma12_rank1.py` shows its actual first commit is `82c768c`,
2026-07-02 ("X-bookmark trading-edge scan 2026-07-02 + Tier-A gate-v2") — three months
later than documented. This doesn't change anything in this PR's scope (no config/doc
narrative edit was requested), but Amo should know the "pre-2026-04-02" dating in
`engine/CLAUDE.md`'s Active Instruments section is inaccurate if he relies on it later.

## New artifacts

| File | What |
|---|---|
| `engine/backtest/run_qqq_sma12_rank1.py` | Backtest + gate-v2 runner, QQQ |
| `engine/backtest/run_aapl_sma12_rank1.py` | Backtest + gate-v2 runner, AAPL |
| `engine/backtest/run_tsla_sma12_rank1.py` | Backtest + gate-v2 runner, TSLA |
| `engine/data/research_verdicts/QQQ_research_equity_trend_rank1.json` | Tracked gate-v2 verdict (real pipeline output) |
| `engine/data/research_verdicts/AAPL_research_equity_trend_rank1.json` | Tracked gate-v2 verdict |
| `engine/data/research_verdicts/TSLA_research_equity_trend_rank1.json` | Tracked gate-v2 verdict |
| `engine/data/research_reports/{QQQ,AAPL,TSLA}_sma12momentum_rank1.json` | Full statistical report (gitignored, same as SPY's) |
| `docs/research/{QQQ,AAPL,TSLA}_sma12momentum_rank1.gate_v2.json` | Committed copy of the full report (mirrors the SPY precedent's `docs/research/SPY_sma12momentum_rank1.gate_v2.json` — see `.gitignore`'s comment that `docs/research/` is part of the committed record alongside `research_verdicts/`, since `research_reports/` itself is gitignored) |
| `engine/tests/test_run_equity_sma12_scripts.py` | Smoke test for the three new runners |
| `engine/scripts/audit_polygon_contamination.py` (modified, additive) | Added `AAPL`/`TSLA` price-band entries to `FUTURES_PRICE_BAND` — required by the pre-existing `test_cache_contamination_audit.py::test_no_contaminated_cache_files` regression test, which fails loudly (by design) whenever a new symbol's cache CSV has no band on file. `QQQ` already had a band. No existing band value changed. |

Research verdicts land in `engine/data/research_verdicts/` (tracked) — the same
namespace SPY's four scripts write to, and explicitly **not**
`engine/data/gate_v2_verdicts/`, the production directory
`gate_v2_policy.is_strategy_authorized` reads for routing (see
`engine/backtest/research_verdict.py`'s module docstring). A research FAIL here cannot
be mistaken for, or accidentally wired into, a live authorization check.

## Strategy and pipeline used, and why

All three new scripts adapt `run_spy_sma12_rank1.py` unchanged: **long the symbol while
monthly close > 12-month SMA, flat to cash otherwise**, monthly rebalance, no other
parameters. This is the simplest and most parameter-light of SPY's four templates, which
makes it the most defensible common strategy to apply identically across three different
underlyings for an apples-to-apples read — rather than picking a different, more
elaborate strategy per symbol, which would make the three verdicts harder to compare and
would itself be a new, unreviewed methodology choice.

Verdicts run through the exact same pipeline SPY's scripts use:
`engine/scripts/validate_strategy.py`'s `validate()` (bootstrap PF, moving-block
bootstrap, Monte Carlo drawdown, deflated Sharpe) feeding `_evaluate_gate_v2()` (the
dual-pathway CORE/ALT gate-v2 rule also used by the live futures pipeline). No
`strategy_class` argument is passed to `_evaluate_gate_v2()` — matching all four SPY
scripts exactly — so, like SPY, these verdicts score against the **strict
intraday-futures Monte-Carlo drawdown ceiling** (currently 5% core / 4% alt via
`GATE_MC_DD_CORE`/`GATE_MC_DD_ALT`), not the wider 25%/30% `equity_swing` ceiling that
exists in `validate_strategy.py`'s `STRATEGY_CLASS_DD` map. This is a pre-existing
choice already baked into the SPY precedent, not something introduced here — see
"Open question" below.

Data source: `backtest/free_daily_export.py` (yfinance primary, Stooq fallback, no API
key) — daily OHLCV, full available history per symbol (QQQ from 1999, AAPL from 1980,
TSLA from 2010, through 2026-08-14). Cached under `engine/backtest/cache/` (gitignored,
same as SPY's cache CSV); re-run
`.venv/Scripts/python -m backtest.free_daily_export --symbols QQQ AAPL TSLA` to refresh.

## Data source/timeframe confirmation (per task step 2)

The live options/equities scanner does **not** use daily bars for QQQ/AAPL/TSLA. Reading
`engine/scanner/signal_scanner.py:454-458`, every scanned symbol — futures and equities
alike — calls `trading_pipeline.analyze_and_decide(symbol, is_futures=<bool>,
timeframe="1h")`. `is_futures=False` changes which broker/contract path and market-hours
gate apply (`market_data.py`'s `get_bars()` waterfall: TradingView MCP -> IBKR -> Polygon
-> CSV cache, same for equities), but the **timeframe is still hourly** — the futures
convention *does* apply here, contrary to what "options underlyings" might suggest.

That matters for reading these results honestly: **this backtest does not validate the
live hourly LLM-pipeline decision process that actually generates QQQ/AAPL/TSLA's paper
fills.** It validates a much simpler question — does a long-only 12-month trend filter
have edge on this underlying? — using the same daily/monthly methodology SPY's four
scripts already established as the working precedent for this validation-gap class.
Building a backtest harness that replays the live 5-stage debate pipeline bar-by-bar
would be a materially larger, unreviewed undertaking and is out of scope here (see "Open
question").

## Results

| Symbol | Verdict | pf_ci_lower (>=1.10) | p_edge (>=0.95) | mc_95th_dd_pct (<=5.0) | dsr (>=0.10) | n in-market months |
|---|---|---|---|---|---|---|
| SPY (existing, 2026-07-02, scored at the then-current 6.0% ceiling) | **FAIL** | 1.7385 PASS | 1.0000 PASS | 21.91 FAIL | 1.0000 PASS | — |
| QQQ (this PR) | **FAIL** | 1.4846 PASS | 0.9996 PASS | 33.65 FAIL | 0.0000 FAIL | 232 |
| AAPL (this PR) | **FAIL** | 1.3065 PASS | 1.0000 PASS | 75.56 FAIL | 0.0000 FAIL | 354 |
| TSLA (this PR) | **FAIL** | 1.0824 FAIL | 0.9905 PASS | 86.83 FAIL | 0.0000 FAIL | 120 |

All four names FAIL core gate v2 (alt path UNSCORED for all — no rolling-WFO /
fixed-params / cost-sweep aux evidence was generated, matching the SPY precedent).

- **Every symbol fails the Monte-Carlo drawdown ceiling by a wide margin.** This is the
  expected shape for a long-only equity trend overlay scored against a ceiling built for
  micro-futures with a $5K/instrument kill switch — see "Open question" for why this
  wasn't rescored on the wider equity ceiling.
- **QQQ, AAPL, and TSLA additionally fail on DSR = 0.0** (deflated Sharpe collapses to
  the degenerate floor once the observed edge is judged against the 12-combination
  expected-max-Sharpe-by-chance correction) — SPY's sma12 DSR was 1.0. This is the
  sharper, more informative difference between SPY and the other three: on this specific
  strategy, SPY's edge clears the multiple-testing bar and QQQ/AAPL/TSLA's does not.
  TSLA additionally fails the PF confidence-interval floor outright (1.0824 < 1.10).
- Buy-and-hold beat the strategy on CAGR and final multiple for all three new symbols
  (as it also did for SPY) — the 12-month SMA filter mainly worked as a drawdown
  reducer relative to buy-and-hold, and even that benefit is inconsistent (AAPL and
  TSLA strategy max-DD is close to or worse than buy-and-hold's).

## Comparison to current status

| Symbol | Before this PR | After this PR | Live paper trading status |
|---|---|---|---|
| SPY | REJECTED (WFE 0.00, 2026-04-02 row) + a separate FAIL sma12 gate-v2 verdict on file | unchanged | Trading as-is (2026-08-03 decision) |
| QQQ | No verdict of any kind on file | FAIL gate-v2 verdict on file | Trading as-is (2026-08-03 decision) — **unchanged by this PR** |
| AAPL | No verdict of any kind on file | FAIL gate-v2 verdict on file | Trading as-is (2026-08-03 decision) — **unchanged by this PR** |
| TSLA | No verdict of any kind on file | FAIL gate-v2 verdict on file | Trading as-is (2026-08-03 decision) — **unchanged by this PR** |

Before this PR, QQQ/AAPL/TSLA were in a strictly worse epistemic position than SPY: SPY
at least had a documented (if failing) rationale on file, while QQQ/AAPL/TSLA had none —
an absent verdict, not a failing one, per `engine/CLAUDE.md`. After this PR, all four
equities names are in the same position: each has a real, current, FAIL gate-v2 verdict
on file, using the actual production statistical pipeline, and none of that changes what
is currently authorized to trade. The decision on what (if anything) to do about four
FAILs sitting under four symbols that trade anyway remains Amo's, unchanged by this PR.

## Open question (per task instructions — flagging, not deciding)

**Should QQQ/AAPL/TSLA (and, by extension, SPY) be scored against the `equity_swing`
25%/30% Monte-Carlo drawdown ceiling in `validate_strategy.py`'s `STRATEGY_CLASS_DD`
map instead of the default `intraday_futures` 5%/4% ceiling?** This is not a new
question raised by this PR — it is the exact question the original 2026-07-02
X-bookmark-scan PR already raised and explicitly deferred (see
`docs/research/README-bookmark-edge-scan-2026-07-02.md`, "Equity-strategy-class DD
threshold — analysis (NOT applied)": *"Not applied here: `_gate_v2_helpers.py` is a
`[safety-review]`-adjacent constant governing what can route to capital. Changing it is
a deliberate risk decision, not an automated PR edit."*). The `equity_swing` class (25%
core / 30% alt) already exists in `validate_strategy.py`'s `STRATEGY_CLASS_DD` map —
apparently built in response to that recommendation — but no run script, SPY's or these
three, actually passes `strategy_class="equity_swing"` into `_evaluate_gate_v2()`. All
of them, including this PR's three, still score against the default strict ceiling.

Re-scoring under each ceiling, using the same-shape table as the 2026-07-02 precedent:

| Symbol | mc_95th_dd_pct | DD @ 5%/4% (current, used above) | DD @ 25%/30% (`equity_swing`) | DSR (class-independent) | Would flip to PASS under `equity_swing`? |
|---|---|---|---|---|---|
| SPY sma12 (2026-07-02 run, then-current 6% ceiling) | 21.91 | FAIL | **PASS** | 1.0000 PASS | Yes — 3/4 CORE otherwise already passed |
| QQQ (this PR) | 33.65 | FAIL | FAIL (>25/30 either way) | 0.0000 FAIL | No |
| AAPL (this PR) | 75.56 | FAIL | FAIL | 0.0000 FAIL | No |
| TSLA (this PR) | 86.83 | FAIL | FAIL | 0.0000 FAIL | No |

**Unlike SPY's sma12 result, none of QQQ/AAPL/TSLA would flip to PASS even under the
widest ceiling already sitting in the codebase.** Their MC-95th drawdowns (34-87%) blow
through the 30% alt ceiling on their own, and all three independently fail the
class-independent DSR floor (0.0 vs 0.10 required) — DSR does not get a class discount
under any existing mechanism in this codebase. So this open question, while real and
worth Amo's attention for SPY, does not change today's bottom line for QQQ/AAPL/TSLA:
FAIL either way.

This task's instructions are explicit that a genuine, un-confident design/threshold call
should default to the most conservative, clearly-defensible option rather than being
silently picked. **The conservative choice made here: leave the ceiling exactly as the
existing SPY precedent already set it** (no `strategy_class` argument, i.e. the strict
intraday-futures ceiling) rather than resolve, inside this PR, a classification decision
that a prior PR already explicitly flagged as Amo's Tier-3 call to make, not an
automated one.

## Verification level

`unit-tested` + `ran and observed output`: each of the three new scripts was executed
end-to-end against real fetched market data (yfinance, current through 2026-08-14) and
the printed/written verdict JSON was read back and is reproduced verbatim in the Results
table above. A smoke test (`engine/tests/test_run_equity_sma12_scripts.py`) additionally
runs each script's `main()` against a small synthetic CSV to catch import/argparse/IO
regressions in CI without depending on network access. This does **not** verify anything
about live scanner/routing behavior — no config or routing code was touched, so there
was nothing live to verify against.

Full suite (`pytest tests/ -q`, 8900+ tests) was run twice against this branch. The first
full run surfaced one genuine new failure directly caused by this PR:
`test_cache_contamination_audit.py::test_no_contaminated_cache_files` failed because the
new AAPL/TSLA cache CSVs had no entry in `FUTURES_PRICE_BAND` — exactly the failure mode
that test is designed to surface (see its assertion message: "Add the symbol to
FUTURES_PRICE_BAND..."). Fixed by adding the two missing band entries (additive only, no
existing band changed); the test was re-run in isolation and passes. A second full run
was then executed to confirm no other regression: see the PR description for the final
count. The two `test_databento_adapter.py::TestMissingPackage` failures present in both
runs are the pre-declared, known local-venv drift (databento is actually importable in
this shared venv, so the test's "not installed" assumption doesn't hold) — unrelated to
this PR's changes, not fixed here per the task's explicit scope.
