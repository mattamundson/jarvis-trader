# Worktree classification - 2026-08-16

Purpose: preserve the current JARVIS Trader state without sweeping unrelated/generated files into one commit.

Branch: `feat/dashboard-hardening-20260813`

## Commit candidate cluster A - broker reconciliation and dashboard truthfulness

These files appear to belong together and should be reviewed/committed as one semantic change after targeted tests pass:

- `engine/api/models.py`
- `engine/routers/brokers_router.py`
- `engine/tests/test_brokers_reconciliation_qty.py`
- `engine/tests/test_brokers_position_avg_price_multiplier.py`
- `dashboard/components/BrokerPositionsWidget.tsx`
- `dashboard/components/ReconciliationWidget.tsx`
- `dashboard/lib/reconciliation.ts`
- `dashboard/tests/reconciliationAdapter.node.test.ts`

Reason: these implement and test the broker-position reconciliation contract, especially the Schwab `disabled_by_policy` / `paper_unverified` distinction.

## Commit candidate cluster B - runtime health, IB freshness, and blind-state checks

These files appear to belong together and should be reviewed/committed as one semantic change after engine tests pass:

- `engine/routers/health_router.py`
- `engine/services/ib_freshness_heartbeat.py`
- `engine/execution/ib_gateway.py`
- `engine/tests/test_health_snapshot_cache.py`
- `engine/tests/test_ib_blind_chaos.py`
- `engine/tests/test_ib_freshness_heartbeat.py`
- `engine/tests/test_health_data_leg_roundtrip.py`
- `engine/tests/test_ib_gateway_execution_leg_roundtrip.py`

Reason: these harden the engine's ability to report whether IB/data/execution state is fresh and actually queryable.

## Commit candidate cluster C - dashboard deploy/runtime validation

These files appear to belong together and should be reviewed/committed as one semantic change after dashboard validation passes:

- `dashboard/scripts/deploy-local.ps1`
- `dashboard/package.json`
- `dashboard/scripts/check-runtime-contract.mjs`
- `dashboard/ecosystem.config.js`

Reason: these make local dashboard deployment and PM2 restarts more reliable, including runtime env loading and stale-code contract checks.

## Commit candidate cluster D - market-data/reaction watcher hardening

These files need a separate review because they touch execution-adjacent behavior:

- `engine/data/market_data.py`
- `engine/discord/reaction_watcher.py`
- `engine/tests/test_reaction_watcher.py`

Reason: these affect live data/reaction handling and should not be hidden inside dashboard or PM2 reliability commits.

## Commit candidate cluster E - secret/key tooling hygiene

These files need explicit review before commit:

- `.mcp.json`
- `engine/.env.example`
- `scripts/rotate_dev_api_key.py`

Reason: these touch MCP configuration, env templates, or key rotation behavior. Values must be redacted/placeholder-only before commit.

## Delete/credential-remediation cluster

These tracked files are currently deleted:

- `Secret-Value.csv`
- `Secret-Value (1).csv`

Reason: the filenames indicate secret material. Do not restore or print contents during normal triage. Treat deletion as likely intentional credential remediation unless proven otherwise.

## Generated/runtime artifacts - do not commit by default

These should generally remain untracked or be archived if they are useful evidence:

- `dashboard/performance.sqlite`
- `engine/.venv-311/`
- `worktree_list.txt`
- `engine/data/morning_forecasts/*.json`
- `engine/data/forecast_reports/*.md`

Reason: these are generated/runtime outputs or local environment artifacts. The `.gitignore` update in this session now suppresses the obvious runtime noise: `engine/.venv-*/`, `*.sqlite`, and `/worktree_list.txt`.

## Documentation/research artifacts - review individually

These may be worth keeping, but should not be bundled with code changes:

- `docs/backlog/DASHBOARD_BACKLOG_2026-08-05.md`
- `docs/repo-integrations/mattamundson__autotrade.md`
- `docs/session-logs/CONVERSATION_2026-08-13_dashboard-hardening.md`
- `docs/session-logs/CONVERSATION_2026-08-13_jarvis-dashboard-vision.md`
- `docs/session-logs/FULL_TRANSCRIPT_2026-08-15_155ea9ad.md`
- `.claude/skills/grok-research/SKILL.md`

Reason: these are project knowledge assets, but they need separate review for size, sensitivity, and long-term location before commit.

## Generated strategy artifact - quarantine/review

- `engine/strategies/generated/llm_strategy_1.py`

Reason: generated strategy code should enter through the strategy funnel: hypothesis, data requirement, backtest, robustness, paper simulation, broker feasibility, and risk gate. Do not treat it as approved trading logic.

## Recommended commit order

1. `.gitignore` + this classification document.
2. Broker reconciliation/dashboard truthfulness cluster.
3. Runtime health/IB freshness cluster.
4. Dashboard deploy/runtime validation cluster.
5. Market-data/reaction watcher hardening cluster.
6. Secret/key tooling hygiene cluster only after redacted review.
7. Documentation/research artifacts only after sensitivity review.

## Required validation before claiming preserved state

- `git status --short` shows generated runtime noise reduced.
- Dashboard: `pnpm run typecheck`, `pnpm run test:unit`, `pnpm run check:runtime-contract`.
- Engine: targeted pytest for changed broker/health/IB/reaction watcher tests before each commit cluster.
- Live service check: `http://127.0.0.1:8010/health`, dashboard proxy health, and dashboard broker positions endpoint.
