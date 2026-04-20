# Worktree Triage - 2026-04-11 11:52 America/Chicago

## Summary

The repo is not in a state where broad staging is safe. The current dirty tree breaks into a few coherent buckets plus a large amount of generated or archival clutter.

## Buckets

### 1. Dashboard proxy/websocket bucket

Modified tracked files:
- dashboard/app/page.tsx
- dashboard/components/command-center/CommandCenterShell.tsx
- dashboard/hooks/useWebSocket.ts
- dashboard/lib/engine-websocket-context.tsx
- dashboard/lib/use-websocket.ts
- dashboard/next.config.ts

Build artifact to exclude:
- dashboard/tsconfig.tsbuildinfo

Untracked likely-related source:
- dashboard/app/api/engine/[...path]/route.ts

Assessment:
- This looks like one coherent dashboard/proxy feature/fix area.
- Port 3010 is up and returning HTTP 200, so this is the cleanest candidate for the next focused review or commit.

### 2. Docs/runbooks/strategy bucket

Modified tracked files:
- docs/CURRENT_STATE.md
- docs/runbooks/HEALTH_API_CONTRACT.md
- docs/runbooks/IB_RECONNECT_AND_HEALTH.md
- docs/runbooks/P0_PAPER_IB_VERIFICATION.md
- docs/runbooks/PAPER_SOURCE_OF_TRUTH.md
- docs/strategic/01_EXECUTIVE_BRIEF.md
- docs/strategic/04_SWOT_AND_STRATEGY.md
- docs/strategic/05_RISK_REGISTER.md
- docs/strategic/07_EXECUTION_SPINE.md

Untracked likely-related docs:
- docs/runbooks/MARKET_DATA_WATERFALL.md
- docs/research/hermes-workspace-notes.md
- docs/strategy/JARVIS-STRATEGY-v1.md
- docs/session-logs/*.md
- docs/token-analysis.html
- docs/usage-report.html

Assessment:
- This is mostly safe to review separately from code.
- The session-log markdown files are archival and should not be mixed with product code commits unless the goal is a docs-only handoff commit.

### 3. Engine approval/openclaw/pipeline/runtime bucket

Modified tracked files:
- engine/agents/pipeline.py
- engine/agents/technical_analyst.py
- engine/agents/trader.py
- engine/config.py
- engine/database/_mixins_alerts.py
- engine/database/migrations.py
- engine/dependencies.py
- engine/llm/client.py
- engine/main.py
- engine/notifications/openclaw_notifier.py
- engine/routers/approval_router.py
- engine/routers/openclaw_router.py
- engine/routers/pipeline_router.py
- engine/routers/portfolio_router.py
- engine/scanner/signal_scanner.py
- engine/scripts/verify_p0_paper_ib.py
- engine/tests/test_api_contract_minimal.py
- engine/tests/test_config_validation.py
- engine/tests/test_pipeline_run_human_gate.py
- engine/tests/test_portfolio_paper_trade_post.py
- engine/tests/test_routes_wired.py
- engine/requirements-core.txt
- engine/requirements.txt

Untracked likely-related source:
- engine/approval/service.py
- engine/db/migrations/0001_add_sessions_threads.sql
- engine/db/session_manager.py
- engine/notifications/pipeline_alert_cooldown.py
- engine/notifications/supervisor.py
- engine/notifications/supervisor_prompts.py
- engine/risk/tool_inspector.py
- engine/services/recipe_loader.py
- engine/utils/context_mgmt.py
- engine/utils/token_optimizer.py
- engine/tests/test_approval_service.py
- engine/tests/test_context_mgmt.py
- engine/tests/test_ib_reconnect_contract.py
- engine/tests/test_market_data_waterfall.py
- engine/tests/test_new_features.py
- engine/tests/test_paper_ledger_pnl_consistency.py
- engine/tests/test_pipeline_alert_cooldown.py
- engine/tests/test_recipe_loader.py
- engine/tests/test_scanner_pause_responsiveness.py
- engine/tests/test_session_manager.py
- engine/tests/test_tool_inspector.py
- engine/recipes/README.md
- engine/recipes/mcl_crude_long_hp.yaml
- engine/thinkorswim-scripts/JARVIS_Regime_MCP_Output.pine
- engine/agents/managed_agent_bridge.py

Assessment:
- This is the largest and riskiest bucket.
- It probably contains multiple sub-features and should not be committed without deeper slicing.
- `engine/config.py` plus `engine/tests/test_config_validation.py` specifically need policy reconciliation because the hard cap on `MAX_CONTRACTS_PER_INSTRUMENT` appears to have diverged from the test expectation.

### 4. Runtime/generated artifacts bucket

Modified tracked files to keep out of commits by default:
- data/jarvis_trader.db
- engine/data/paper_trades.json
- engine/learning/data/session_memory.json
- .claude/task-manifest.json
- dashboard/tsconfig.tsbuildinfo

Untracked generated/runtime clutter:
- data/jarvis_trader.db.orphaned-20260410-stage2
- career_ops.db
- engine/data/strategy_state.json
- engine/test_output.txt

Assessment:
- These should be excluded from any normal code commit.
- If they are not supposed to be tracked, `.gitignore` needs follow-up.

### 5. Archive/import clutter bucket

Untracked bulk directories:
- .claude-backup-20260410_085914/
- .claude-backup-20260410_085927/
- agent-reach-claude-code-bundle/
- jarvis_trader_handoff_bundle/
- n-autoresearch-skill/

Assessment:
- These are archival/import bundles, not active app code.
- They massively inflate `git status` noise and should be kept out of normal feature commits.

## Recommended next commit order

1. Dashboard bucket only, excluding `dashboard/tsconfig.tsbuildinfo`
2. Docs bucket only, if the goal is doc refresh
3. Engine approval/openclaw/pipeline bucket, but only after file-by-file slicing and test-baseline review
4. Separate housekeeping commit for `.gitignore` if the team wants runtime/build artifacts ignored

## Hard do-not-stage list

- data/jarvis_trader.db
- engine/data/paper_trades.json
- engine/learning/data/session_memory.json
- dashboard/tsconfig.tsbuildinfo
- .claude/task-manifest.json
- archive/import directories under `.claude-backup-*`, `agent-reach-claude-code-bundle/`, `jarvis_trader_handoff_bundle/`, `n-autoresearch-skill/`

## Best immediate follow-up

If continuing right now, review the dashboard bucket first. It is small, running locally on port 3010, and isolated enough to validate without mixing engine runtime churn.
