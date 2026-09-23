# Market Brief Production Strategy — Machine Score → Dashboard → Calibrated Probabilities

## Final goal
Build a verifiable, analysis-only morning market intelligence system that turns the generated COrey-grade machine-scored brief into an operator-facing Mission Control card, then upgrades its continuation / rotation / failure probabilities from deterministic heuristics into historically calibrated probabilities.

The end state is:

1. **Dashboard-visible:** Mission Control shows broad-market machine-score context beside runtime truth and SPX intraday analysis.
2. **Evidence-preserving:** Every displayed number has a source artifact, a parser contract, and stale/degraded behavior.
3. **Reviewable:** The dashboard card is in a clean branch + PR with typecheck/build/unit/E2E/API evidence.
4. **Statistically honest:** The next tranche creates a calibration dataset and target definitions so probabilities can eventually be scored with Brier/log-loss/reliability bins instead of narrative confidence.
5. **Safe:** No live trading, broker routing, risk config, kill-switch, `.env`, or symbol-gate mutation occurs. The system is decision-support only.

## Why we are accomplishing this
Amo asked for a morning market update with Corey-style structural insight, but better: more accurate, more transparent, and reusable. The prior artifact proved the model can generate a machine-scored brief, but a Markdown file alone is not enough for market-hours operation. It must be visible where decisions are made, display source quality, fail safely when stale, and avoid pretending heuristic probabilities are statistically proven.

This strategy converts the work from a one-off report into a dashboard-backed, test-gated pipeline:

- **Before:** A generated Markdown preview with useful probabilities but no UI contract.
- **Now:** A Mission Control card with source-quality and machine-payload parsing.
- **Next:** A calibration dataset that compares historical score states to actual open-to-close outcomes.

## What this accomplishes

### Operator impact
- Amo can glance at Mission Control and see broad-market context without opening a report file.
- The card separates continuation / rotation / failure odds rather than burying confidence in prose.
- SPY, QQQ, VIX, ES, and NQ are shown together so risk-off/risk-on alignment is explicit.
- Stale/degraded states are visible; bad data does not silently render as confident guidance.

### Engineering impact
- Adds a typed dashboard contract for the market-brief payload.
- Adds parser tests so future report-format changes cannot silently break the card.
- Adds fresh-server Playwright coverage so the card is verified against the current production build.
- Creates a PR-ready branch from a clean worktree rather than polluting the serving tree.

### Quant/research impact
- Establishes the measurement boundary for future calibration:
  - Score timestamp
  - Input state: trend_score, vol_score, macro_score, probabilities
  - Realized outcome: continuation / rotation / failure over a defined horizon
  - Metrics: Brier score, log loss, reliability bins, calibration slope/intercept
- Keeps heuristic probabilities labeled as such until calibration is actually run.

## Implementation phases

### Phase 1 — Dashboard card preservation + PR
**Goal:** preserve the verified dashboard work in a PR so it can be reviewed/merged without touching the live serving tree directly.

Steps:
1. Confirm clean worktree and branch state.
2. Sync branch with latest `origin/master` because branch is currently behind.
3. Resolve any conflicts with dashboard route/card/tests.
4. Re-run verification:
   - `pnpm exec tsc --noEmit --pretty false`
   - `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/marketBrief.node.test.ts`
   - `pnpm run build`
   - `pnpm exec playwright test tests/e2e/mission-control-market-brief.spec.ts --config=playwright.fresh.config.ts`
   - Isolated `next start -p <free port>` + real `GET /api/market-brief`
5. Push branch.
6. Open PR with:
   - Scope summary
   - Safety boundary
   - Verification receipts
   - Explicit note: no live engine/risk/kill-switch/env/symbol-gate changes.
7. Verify PR metadata/files with `gh pr view` / `gh pr diff --name-only`.

Acceptance criteria:
- PR exists and points to only the intended dashboard/report files.
- Local verification remains green after sync.
- PR body contains complete evidence.
- No protected runtime config files are present in PR diff.

### Phase 2 — Calibration design and dataset contract
**Goal:** define exactly what continuation / rotation / failure mean and identify the dataset required to calibrate the probabilities.

Definitions to lock:
- **Continuation:** downside/risk-off thesis confirms after the brief timestamp; example for a risk-off state: ES/NQ/SPY/QQQ remain below pivot/control and close lower or fail reclaim windows.
- **Rotation:** market re-enters balanced/choppy state; pivots are reclaimed or price closes inside control without follow-through.
- **Failure:** the initial thesis fails materially; risk-off brief followed by strong reclaim/squeeze or risk-on close.

Data required:
- Historical generated score payloads, if available.
- If historical payloads are sparse, reconstruct payload-like features from daily/intraday bars:
  - SPY, QQQ, ^VIX, ES=F, NQ=F, MES=F
  - Prev close, current/preopen close, gap pct, pivots, VIX delta, macro event count where available.
- Realized outcome labels for the chosen horizon.

Acceptance criteria:
- A documented schema for calibration rows.
- A first-pass script or fixture that can compute labels on historical bars without touching live trading.
- A report that lists data gaps and whether calibration can proceed with current local data.

### Phase 3 — Calibration implementation
**Goal:** replace or supplement heuristic probabilities with calibrated outputs.

Steps:
1. Build feature generator from historical bars.
2. Build labeler for continuation/rotation/failure.
3. Replay existing heuristic scoring over historical rows.
4. Evaluate:
   - Brier score per class
   - Log loss
   - Reliability bins
   - Confusion matrix of dominant class
   - Base-rate comparison
5. Fit simple calibration layer only if enough samples exist:
   - Isotonic or Platt-style logistic calibration for dominant probability
   - Or conservative shrinkage toward base rates if sample is small.
6. Emit calibrated coefficients / lookup table as analysis-only artifact.
7. Add tests proving probabilities sum to 100, stale data degrades, and touch/close logic stays ordered where relevant.

Acceptance criteria:
- Calibration report includes sample count, date span, outcome base rates, Brier/log-loss, and reliability bins.
- If sample count is insufficient, the report says so and refuses to overfit.
- Dashboard clearly distinguishes `heuristic` vs `calibrated` model version.

### Phase 4 — Optional controlled deploy
**Goal:** place the card on the live serving dashboard after PR review/merge or explicit deploy authorization.

Steps:
1. Use canonical deploy flow, not dirty-tree edits.
2. Build cleanly.
3. Restart only `jarvis-dashboard`.
4. Verify authenticated `/mission-control` and `/api/market-brief`.
5. Update `DASHBOARD_STATE.md`.

Acceptance criteria:
- Live dashboard card visible.
- `/api/market-brief` returns HTTP 200 with analysis-only flags.
- No engine restart, broker action, risk config, kill-switch, `.env`, or symbol gate changes.

## Risk controls
- [RISK] Live trading/risk/kill-switch changes require a `[safety-review]` PR. This strategy avoids those files entirely.
- [RISK] Heuristic probabilities must not be marketed as calibrated edge. The dashboard currently displays machine-score outputs; calibration work will explicitly label model status.
- [RISK] GitHub Actions are known to have startup failures on this estate. Local verification remains necessary evidence; PR CI state must be reported honestly.
- [RISK] Dirty canonical serving tree must not be used as authority. All code work uses clean worktrees.

## Verification gates
Every code tranche must provide:
1. Exact command run.
2. Exit code/result.
3. Scope verified.
4. Artifact path or PR URL.

Minimum for dashboard PR:
- TypeScript typecheck.
- Node parser tests.
- Production build.
- Fresh-server Playwright targeted smoke.
- Real API route smoke against the current artifact.

Minimum for calibration tranche:
- Script compile/test.
- Fixture label tests.
- Report artifact with data span/sample count/base rates.
- No live trading/risk/kill-switch/env changes.

## Loop operating rule
Continue in priority order until the final goal is complete or a real blocker appears:
1. Sync and PR the dashboard card.
2. Verify PR file scope and checks.
3. Start calibration data discovery.
4. If enough historical data exists, implement first calibration report.
5. If insufficient data exists, produce the data-gap report and next collection step.

## Current known starting point
- Local commit before this plan: `c63b5fe8 feat(dashboard): add market brief machine-score card`.
- Branch status before sync: `ahead 1, behind 4` relative to `origin/master`.
- Verified earlier: tsc, node tests, build, fresh Playwright, isolated API smoke all passed.
