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
- **PR #75 `integration/master-converge-2026-06-16 -> master`** brings the WARN
  directive (plus operational config) onto master so master becomes bootable.
  **#75 is the gate to running master.**
- **Do NOT flip `.env REQUIRE_HUMAN_APPROVAL` to force boot.** That bypasses the
  documented startup contract; the correct fix is merging #75.

## State of #75 (verified 2026-06-16)

CI is green except **Engine Tests (pytest, slow)** -- 2 failures remain. The
peer's HEAD commit `f757673` already aligned the 4 fast safety tests. The
Safety-critical config gate **passes** (the `[safety-review]` tag is present).

The 2 remaining slow failures, diagnosed:

1. `test_approval_to_order_e2e.py::test_kill_switch_blocks_approve`
   - Approve returns **409 (blocked)** -- but with detail "MNQ is not authorized
     for paper orders" (the paper_config / validation-only gate) instead of the
     kill-switch reason. For the unvalidated symbol MNQ, the validation gate
     fires **before** the kill-switch check, so the test's "mention kill switch"
     assertion fails even though the order is correctly blocked.
   - **This is NOT a safety regression.** The kill switch is sound:
     `SafetyLayer.get_status()` emits `is_killed` AND `kill_switch_active` in
     lock-step (explicit CONTRACT at `engine/risk/safety_layer.py:881-896`,
     enforced by `test_kill_switch_status_contract`). The approve path DOES
     return 409.
   - **Open design question for the owner (the one real decision):** should the
     approve gate check the kill switch **before** symbol-validation, so a halted
     system reports the halt rather than the symbol? Either resolution is valid:
     (a) reorder the gate so kill-switch is reported first (safety-code change),
     or (b) adapt the test to use a validated symbol so kill-switch is the binding
     gate. This is the branch owner's call -- do not weaken the kill-switch
     assertion to force a pass.

2. `test_paper_trading_flow.py::test_trading_config_defaults`
   - A config default changed per the 2026-06-15 directive (`assert True is
     False`). Legitimate test alignment -- update the expected default.

## Deploy sequence

1. **[owner/peer] Green #75's 2 slow tests** per the diagnosis above (resolve the
   precedence question, align the config-default test). Confirm
   `gh pr checks 75` all green.
2. **[Amo-gated] Confirm `[safety-review]` is in #75's body** (it modifies 5 risk
   files) -- this is your attestation; the classifier blocks anyone else adding it.
3. **[Amo-gated] Merge #75 into master.**
4. **[Amo-gated] Restart the engine onto master:** `.\restart_engine.ps1`
   (never `--reload`; admin variant `.\restart_engine_admin.ps1` if taskkill
   fails). Steady-state startup ~229s; the script polls `/health`.
5. **[verify] Run the gate:** `pwsh -File scripts\verify-post-restart.ps1`
   -- all hard gates must PASS (see that script for exact criteria).
6. **[Amo-gated, optional] If `ibkr_data_connected=false`:** `POST /data/reconnect`
   (paper port 4002; live 4001 is permanently blocked). TV MCP is the Tier-0 bar
   source, so the engine is not blind without it.
7. **[follow-on] Merge surfacing PRs once master is verified:** jarvis #74
   (north-star surfacing) and amo #72 (north-star surfacing -> main).

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
- `/analytics/excursion` (conditional -- only if the post-trade WS4 lands; needs
  a one-time `engine/analytics/excursion_backfill.py` run).

## Gating summary (who does what)

| Step | Owner |
|---|---|
| Green #75's 2 slow tests | peer/owner of the convergence branch |
| `[safety-review]` tag + merge #75 | Amo only |
| `restart_engine.ps1` | Amo only |
| `POST /data/reconnect` (if IB data down) | Amo only |
| Run `verify-post-restart.ps1` | anyone (read-only) |
| Merge surfacing PRs #74 / amo #72 | Amo only |
