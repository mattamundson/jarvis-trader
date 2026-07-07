# Master-convergence deploy runbook (2026-06-16)

Deploy the already-merged forward-test / decision-identity spine + the top-10
surfacing batch onto the **running** engine. Everything below the "Amo-gated"
markers is an owner action. This runbook is paired with
`scripts/verify-post-restart.ps1` (the post-restart verification gate).

## Why a runbook (the boot trap)

- The decision-identity spine (old PRs #59/#61-#65) is **already merged to master**
  via consolidation `7407e36` (PR #71). Ralph loop #72 merged US-001..010
  surfacing; IB auto-reconnect (#68) and cache reconciliation (#69) also landed.
  **The code is on master.**
- The **live engine runs `feat/family-fdr-campaign`, NOT master.** Switching to
  master crash-loops: master still carries the old boot-blocking
  `REQUIRE_HUMAN_APPROVAL = FAIL`, while the **2026-06-15 owner directive** that
  relaxes it to a non-blocking `WARN` (autonomous paper) lives only on the feat
  line.
- **PR #75 `integration/master-converge-2026-06-16 -> master`** brought the WARN
  directive (plus operational config) onto master so master became bootable.
  **#75 is now MERGED** (`origin/master` HEAD = `6182f31`, "Merge pull request
  #75"). The boot trap is therefore *closed at the git level* -- master is
  bootable. What remains is the **restart onto master** (Amo-gated).
- **Do NOT flip `.env REQUIRE_HUMAN_APPROVAL` to force boot.** That bypasses the
  documented startup contract; #75 already resolved it the correct way.

## State of #75 (MERGED 2026-06-16)

#75 merged to master. The 2 previously-open slow tests were resolved by the
branch owner before merge. The kill-switch diagnosis is retained here for the
record (it was NOT a safety regression): `SafetyLayer.get_status()` emits
`is_killed` AND `kill_switch_active` in lock-step (CONTRACT at
`engine/risk/safety_layer.py:881-896`, enforced by
`test_kill_switch_status_contract`); the approve path returns 409 (blocked).

## Current live state (verified 2026-06-16 via `verify-post-restart.ps1`)

The engine is **up and healthy but still on the pre-#75 branch** -- the running
process has NOT yet been restarted onto master:

- `status=ok`, `llm_path_healthy=true`, `tradingview_mcp_healthy=true`,
  `health/full overall=healthy` -- the engine is serving.
- `ibkr_data_connected=false` -- IB data leg down (Amo reconnect; TV MCP Tier-0).
- `/forward-test/status`, `/analytics/forward-test`, `/safety/status` return
  null/empty -- **expected**: those spine/master routes light up only after the
  restart onto master. This is the gate honestly reporting "not yet deployed",
  not a failure to fix.

So the single remaining action to activate the merged spine is the **restart**.

## Deploy sequence

1. ~~Green #75's slow tests~~ **DONE** (resolved before merge).
2. ~~Confirm `[safety-review]` on #75~~ **DONE** (merged).
3. ~~Merge #75 into master~~ **DONE** -- `origin/master` = `6182f31`.
4. **[Amo-gated] Restart the engine onto master:** `.\restart_engine.ps1`
   (never `--reload`; admin variant `.\restart_engine_admin.ps1` if taskkill
   fails). Steady-state startup ~229s; the script polls `/health`. **This is the
   one remaining step that activates the merged spine.**
5. **[verify] Run the gate:** `pwsh -File scripts\verify-post-restart.ps1`
   -- all hard gates must PASS (see that script for exact criteria). Pre-restart
   it reports 2 hard fails (safety + forward-test null) by design; those clear
   once the restart lands.
6. **[Amo-gated, optional] If `ibkr_data_connected=false`:** `POST /data/reconnect`
   (paper port 4002; live 4001 is permanently blocked). TV MCP is the Tier-0 bar
   source, so the engine is not blind without it.
7. **[follow-on] Merge surfacing / analytics PRs once master is verified:** jarvis
   #74 (north-star surfacing), **#78 (WS4B post-trade analytics endpoints --
   purely additive, no migration)**, and amo #72 (north-star surfacing -> main).

## What the restart activates

- **Migrations** run at startup (`DatabaseManager.__init__ -> run_migrations()`).
  Confirm via the verification gate / `/system/data-integrity`.
- **Decision-identity stamping + forward-test loop** (consolidated `7407e36`):
  proven live by `/analytics/forward-test` returning a `lineages[]` block and a
  fresh paper trade's `strategy_params.decision_identity`.
- **Forward-test status reader** `/forward-test/status?symbol=MES` (US-003).
- **New routers** registered in `engine/main.py`; **surfacing** (`/health/full`
  per-symbol freshness, LLM provider state, prod-gate scorecard) from #72.

## Verification

After step 4, `scripts/verify-post-restart.ps1` checks (hard gates marked *):
- `/health`* status=ok, llm_path_healthy=true, tradingview_mcp_healthy=true;
  reports ibkr_data_connected + vertex_failover_count.
- `/health/full` not degraded; `/safety/status`* kill switch clear.
- `/brokers/positions` reachable; `/forward-test/status`* returns a status.
- `/analytics/forward-test` exposes `lineages[]` (stamping live).
- `/analytics/excursion` + `/analytics/entry-timing` are on master (migration_040);
  excursion aggregates populate after a one-time `engine/analytics/excursion_backfill.py`
  run. WS4B (#78) adds `/analytics/exit-attribution`, `/slippage-attribution`,
  `/losing-streak`, `/trades/by-regime`, `/trades/{id}/pnl-breakdown` -- all read-only
  over existing columns (no migration), live once #78 merges + the restart lands.

## Gating summary (who does what)

| Step | Owner | Status |
|---|---|---|
| Green #75's slow tests | peer/owner | DONE |
| `[safety-review]` tag + merge #75 | Amo only | DONE (master=6182f31) |
| `restart_engine.ps1` (activates the merged spine) | Amo only | **pending** |
| `POST /data/reconnect` (if IB data down) | Amo only | pending |
| Run `verify-post-restart.ps1` | anyone (read-only) | run pre-restart |
| Merge follow-on PRs #74 / #78 / amo #72 | Amo only | pending |
