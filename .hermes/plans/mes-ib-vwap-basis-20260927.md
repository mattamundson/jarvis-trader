# Plan — MES IB Ladder, Weekly VWAP Acceptance, SPX Basis

## Safety and scope

- Research-only, paper-only, local-first.
- MES is the only futures symbol analyzed operationally.
- MCL and MNQ remain DO_NOT_TRADE_SYMBOLS and are excluded from code paths, datasets, outputs, and examples.
- No edits to the live engine, `engine/config.py`, `engine/risk/**`, execution routing, `.env`, kill switch, or paper/live parameters.
- All work occurs on `research/mes-ib-vwap-basis-20260927` in the isolated worktree `C:/Users/mattm/ThinkorSwim/wt-mes-ib-vwap-basis-20260927`.

## Finish line

Deliver one reproducible, causal research harness and three evidence packages:

1. MES initial-balance sequential-target study.
2. MES weekly-VWAP acceptance study.
3. SPX-to-ES/MES basis translator validation.

Each phase must write machine-readable JSON/CSV plus a concise Markdown report with exact data provenance, assumptions, trial counts, in-sample and chronological walk-forward results, costs, explicit ACCEPT/REJECT/INCONCLUSIVE verdict, and reproduction commands.

## Phase 0 — Data and integrity preflight

1. Audit every candidate MES 5-minute/15-minute cache by actual timestamps, rows, SHA-256, duplicates, NaNs, OHLC invariants, cadence, timezone, and session coverage.
2. Prefer the widest verified 5-minute cache. Merge overlapping caches only if common timestamps have identical OHLCV values; record conflicts and reject an unsafe merge.
3. Define RTH as CME equity-index regular session 08:30–15:00 America/Chicago and overnight as prior trade-date 17:00–08:29:59 CT.
4. Handle DST with timezone-aware conversion; assign futures trade date causally.
5. Freeze selected input provenance in every output.

## Phase 1 — MES initial-balance ladder

### Rules

- IB window: first 60 RTH minutes, 08:30–09:29:59 CT.
- Signals become eligible only after IB is complete; no completed-IB values on pre-09:30 rows.
- Long break: first post-IB bar whose high crosses above IB high. Short break: first post-IB bar whose low crosses below IB low.
- Intrabar fill assumptions are explicit and conservative. Ambiguous same-bar stop/target collisions resolve stop-first.
- Entry variants are preregistered before results: stop-entry at IB boundary plus adverse slippage; close-confirmation entry on first post-IB close beyond the boundary.
- Sequential targets for one unit each: overnight extreme, 0.5× IB extension, 1.0× IB extension. The IB break itself is the entry event; report its unconditional occurrence/base rate separately.
- If the overnight extreme is already beyond/behind the entry in a direction that makes it non-sequential, classify it as already completed and exclude it from executable target order while retaining a descriptive hit field.
- Stop variants: opposite IB extreme and IB midpoint. No optimization beyond this frozen 2×2 entry/stop family.
- Exit remaining units at RTH close.

### Costs

- MES multiplier: $5/point.
- Baseline round-trip commission/fees: $1.42 per contract.
- Baseline slippage: 1 tick per side ($2.50 round trip per contract).
- Stress tiers: 2 and 3 ticks per side.
- Costs charged explicitly per entry/exit unit; trade ledger and equity curve must reconcile to $0.00 residual.

### Metrics and verdict

Report sessions, signals, direction split, target-touch/close rates, MFE, MAE, time-to-target, net P&L, PF, win rate, expectancy, CAGR, max drawdown, observed-frequency Sharpe, and DSR from the candidate's own return series using the true campaign-trial lower bound. Run a chronological 60/40 split plus expanding walk-forward blocks. Benchmark against unconditional target base rates and a simple first-IB-break baseline.

ACCEPT only if the frozen champion is positive net of baseline and +1-tick stress costs in locked OOS, has positive OOS CAGR, PF > 1, DSR >= 0.95 under the true campaign count, positive disjoint halves, and improves on the simple IB-break baseline. Otherwise REJECT; use INCONCLUSIVE only for inadequate sample/data.

## Phase 2 — Weekly-VWAP acceptance

- Weekly VWAP resets Sunday 17:00 CT and uses only bars available through the decision timestamp.
- Baseline: price above developing weekly VWAP at fixed 10:30, 11:30, and 12:30 CT decision times.
- Test separately: time acceptance, volume-above-VWAP fraction, causal developing VPOC, causal completed-period TPO POC, and an OHLCV-only cumulative-delta proxy explicitly labeled as not true bid/ask delta.
- Outcomes are mutually exclusive next-session-close continuation / failure / rotation and probabilities are trailing-only empirical distributions summing to 1.0.
- Expanding walk-forward must pass truncation and future-tampering invariance tests.
- Compare paired multiclass Brier and economic expectancy against both the basic price-above-weekly-VWAP and trailing-unconditional arms.
- Retain only when the paired OOS Brier-improvement CI is wholly above zero and OOS net expectancy exceeds the basic baseline.

## Phase 3 — SPX-to-ES/MES basis translator

- Preserve original SPX strike, timestamp, futures contract/expiry, theoretical basis, observed basis when supplied, translated ES/MES level, input ages, roll state, and selected basis source.
- Theoretical level: `spot * exp((risk_free_rate - dividend_yield) * year_fraction)`.
- Prefer observed basis only when SPX and ES timestamps are synchronized and fresh; otherwise fall back to theoretical carry or fail closed if required inputs are stale.
- Reject expired contracts and flag quarterly roll windows.
- ES and MES share the same index-price level; output differs in symbol metadata, not translated price.
- Validate arithmetic, observed-basis preference, staleness, clock skew, expiry, roll flags, and the Loom 7750-to-approximately-7814 example.

## Verification gates

1. Python compile all new modules.
2. Targeted pytest using `-k`, never overriding safe marker exclusions with `-m`.
3. End-to-end harness run from frozen cache.
4. JSON readback, count reconciliation, probability-sum checks, and $0 trade-ledger reconciliation.
5. Independent recomputation of headline metrics from raw outputs.
6. Ruff on changed files and `git diff --check`.
7. Git scope verification proving no live/risk/kill-switch/.env/DO_NOT_TRADE file changed.

## Expected artifacts

- `engine/backtest/research/mes_ib_vwap_basis_study.py`
- `engine/backtest/research/spx_futures_basis.py`
- targeted tests under `engine/tests/`
- three Markdown reports under `docs/research/`
- JSON/CSV evidence plus manifest under `.hermes/artifacts/mes_ib_vwap_basis_20260927/`
