# Paper Pipeline Trust Closure - 2026-08-28

**Goal:** Make the MES paper pipeline trustworthy enough to collect promotion evidence without confusing green checks for broker, data, or ledger truth.

**Scope:** Paper trading only. No live-trading activation, no engine restart, no safety-limit mutation, no `.env` mutation, and no broker-side action in this phase.

**Current recommended order:** unblock CI, merge already-open trust work, then add runtime evidence contracts that prove paper fills, data, and ledgers agree.

## Executive Recommendation

Proceed with **Paper Pipeline Trust Closure** as the next phase.

The immediate bottleneck is not strategy discovery. It is operational truth: GitHub Actions is account-gated, broker execution health can read stale, IB data and TradingView data have independent lifecycles, and paper ledger truth spans broker, SQLite, and historical JSON paths. Until those are surfaced as one readiness contract, more dashboard or strategy work can make the system look better without making evidence better.

## Phase A - CI And Merge Queue Unblock

**Objective:** Restore the ability to trust PR checks.

1. Fix the GitHub Actions billing/spending-limit gate reported on PRs #744, #745, and #746.
2. Rerun checks on the open PRs.
3. Merge in dependency order:
   - #744 `fix(ci): clear draft gate blockers`
   - #746 `fix(dashboard): repair safety component tests`
   - #745 `feat(analytics): add pipeline funnel card`
   - #738 `fix(dashboard): T3 - 13 audit ERROR routes`
   - #742 `feat(analysis): post-close Corey recap scorecard`
4. Re-check Vercel and branch status after each merge.

**Acceptance:** open PR checks start real jobs, pass, and merged branches are confirmed on `origin/master`.

## Phase B - Paper Readiness Contract

**Objective:** Create one read-only endpoint that says whether the paper pipeline can collect valid evidence.

Initial implementation:

- `GET /readiness/paper-pipeline`
- Inputs: cached `/health` runtime truth plus static paper instrument eligibility.
- Output: `ready`, `degraded`, or `blocked` with named checks.

Required checks:

- Paper mode is active and live trading is off.
- Kill switch is inactive.
- SQLite is connected.
- IB paper execution path is verified, not stale.
- Broker probe is OK.
- At least one sanctioned market-data source is available.
- Market data is fresh for active paper symbols.
- LLM path is healthy.
- Active paper symbols are not in `DO_NOT_TRADE_SYMBOLS`.
- Paper config enabled symbols match active symbols.
- Default briefing symbols cover active symbols.
- Approval queue is clear.

**Acceptance:** endpoint is covered by focused tests and reuses `/health` truth rather than creating a second probe system.

## Phase C - Broker And Data Truth Closure

**Objective:** Eliminate "connected but not actually usable" ambiguity.

1. Use `docs/runbooks/P0_PAPER_IB_VERIFICATION.md` to verify IB Gateway paper port 4002.
2. Confirm `/health` reports:
   - `execution_connected_verified=true`
   - `ib_execution_stale=false`
   - `ibgateway_alive=true`
   - `ibgateway_port=4002`
3. Confirm market-data truth:
   - `market_data_fresh=true`
   - `market_data_stale_symbols=[]`
   - either `ibkr_data_connected=true` or `tradingview_mcp_healthy=true`
4. Add a dashboard card only after the backend readiness endpoint is merged.

**Acceptance:** the paper readiness endpoint moves from `blocked` to `ready` or to a clearly explainable `degraded` state without manual cross-referencing.

## Phase D - Ledger Reconciliation

**Objective:** Prove broker, engine SQLite, and paper reporting agree.

1. Treat `engine/data/jarvis_trader.db` as the canonical dashboard/API ledger per `docs/runbooks/PAPER_SOURCE_OF_TRUTH.md`.
2. Run or extend the paper source reconciliation helper.
3. Add a compact evidence surface showing:
   - broker open positions count
   - SQLite open positions count
   - latest closed trade timestamp
   - lifetime realized PnL from `/pnl/truth`
   - divergence status
4. Do not wire `/pnl/truth` into kill-switch calculations; their windows intentionally differ.

**Acceptance:** a paper fill can be traced from broker state to SQLite state to dashboard/reporting state.

## Phase E - Bracket And Stop Enforcement Evidence

**Objective:** Prove every paper entry has broker-side protection evidence.

1. Add a read-only bracket evidence endpoint or extend an existing broker status surface.
2. For each active paper position, show:
   - parent order id
   - stop order id
   - target order id when applicable
   - broker order status
   - side and quantity match
   - last verification timestamp
3. Treat missing stop proof as `blocked` for promotion evidence.

**Acceptance:** no open paper position can appear "healthy" without explicit stop/target evidence.

## Phase F - Evidence Scorecard

**Objective:** Turn the phase into a promotion-grade evidence trail.

Scorecard rows:

- readiness status
- broker execution truth
- market data freshness
- ledger reconciliation
- bracket protection proof
- MES-only instrument compliance
- Corey recap scorecard availability
- post-close grader verdict availability
- unresolved warnings

**Acceptance:** a single report can answer whether MES paper evidence is valid, incomplete, or contaminated.

## Promotion Criteria

Do not advance beyond this phase until all are true:

- `GET /readiness/paper-pipeline` is `ready` for a sustained evidence window.
- No active paper symbol is halted.
- No broker execution stale state appears during an active paper position.
- Ledger reconciliation shows no unresolved divergence.
- Every open paper position has broker-side stop proof.
- CI is running real jobs and required checks are green.

## Blockers To Track

- GitHub Actions billing/spending-limit gate blocks trustworthy automated checks.
- IB Gateway paper login and socket state are operational prerequisites.
- Any secret/provider credential rotation remains a separate security lane and must not be mixed with readiness-code changes.

## First Implementation Slice

Ship `GET /readiness/paper-pipeline` with tests, then wire a dashboard card only after the backend contract merges cleanly.
