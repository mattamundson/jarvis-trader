# Canonical Dashboard Cutover + Rollback Runbook (2026-09-04)

Status: **PREPARED, NOT EXECUTED.** All commands literal, no placeholders. Execute only with Amo's explicit go-ahead. Safety boundary: no engine/risk/kill-switch config is touched by any step.

## Preconditions (all verified 2026-09-04)

- Canonical serving tree runtime-green: dashboard `:3010` 401/200 auth split, `source_integrity` pass 2/0/0.
- Authority candidate verified: `C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903` on `feat/canonical-authority-cutover-20260903`, tsc + build + fresh Playwright passed.
- Preservation inventory: `docs/session-logs/PRESERVATION_INVENTORY_2026-09-04.md`.
- PM2 binding audit: both apps match canonical ecosystem configs exactly.

## Cutover option A — rebind PM2 to authority candidate build (recommended first step)

```powershell
# 1. Build the authority candidate fresh (already built once; rebuild for certainty)
Set-Location 'C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903/dashboard'
$env:CI = 'true'
node .\node_modules\next\dist\bin\next build

# 2. Copy canonical auth env into authority dashboard (gitignored, single-writer preserved)
Copy-Item 'C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard/.env.local' 'C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903/dashboard/.env.local' -Force

# 3. Stop canonical dashboard supervision
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' delete jarvis-dashboard

# 4. Start authority candidate under PM2 on :3010
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' start 'C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903/dashboard/ecosystem.config.js' --only jarvis-dashboard
# NOTE: authority ecosystem.config.js script/cwd paths must point at the authority tree.
# If they still point at the canonical tree, edit ONLY script/cwd in the authority copy first (source change, commit it).

# 5. Persist + verify
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' save
pwsh.exe -NoProfile -File 'C:/Users/mattm/scripts/jarvis-serving-boundary-check.ps1'
```

Success criteria: boundary check reports 401/200/200/200/200 local + 200/200 tailnet + `source_integrity` pass.

## Rollback (restore canonical serving tree supervision)

```powershell
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' delete jarvis-dashboard
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' start 'C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard/ecosystem.config.js' --only jarvis-dashboard
& 'C:/Users/mattm/AppData/Local/pnpm/pm2.CMD' save
pwsh.exe -NoProfile -File 'C:/Users/mattm/scripts/jarvis-serving-boundary-check.ps1'
```

Rollback safety: canonical `.next` (BUILD_ID `XkrhceydxgJxDzVE`) and `.env.local` remain untouched throughout option A, so rollback is a pure supervision rebind with zero rebuild required.

## Cutover option B — full tree swap (DEFER)

Requires: engine/.env + dashboard/.env.local byte-for-byte copy, engine/.venv reinstall, `.next` rebuild, scheduled-task re-registration, PM2 ecosystem path updates for BOTH apps, and a maintenance window. Do not execute without a dedicated tranche.

## Hard rules

- Never `git reset --hard` the canonical serving tree.
- Never edit `engine/.env` or `dashboard/.env.local` values during cutover (copy only).
- If the boundary check fails after option A, run the rollback block immediately — do not debug forward while `:3010` is degraded.
