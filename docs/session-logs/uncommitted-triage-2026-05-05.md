# Uncommitted Triage — 2026-05-05

**Branch:** `feat/tradingview-mcp-gamma-kraken`
**Diverged:** 43 ahead / 67 behind origin
**Working tree:** 12 modified, 6 untracked entries (4 docs, 1 broken venv dir, 1 data dir)
**Diff stat:** 114 insertions / 16 deletions across 12 files

## Headline finding

The 12 modified files form **two clean, well-scoped commits** plus **one independent dependency pin**:

1. **Engine** (`engine/api/models.py`, `engine/routers/health_router.py`, `engine/routers/brokers_router.py`) — splits the historically-conflated `ibkr_connected` boolean into per-path `ibkr_execution_connected` + `ibkr_data_connected` and surfaces a `health: ok|partial|blind` field on `/brokers/positions` to kill the silent-failure mode where a fully-disconnected reconciliation returned an empty discrepancy list. Directly addresses memory entry `project_health_brokers_ibkr_divergence_2026_05_04` (Recommendation A) and `project_tracker_broker_drift_2026_04_24`.
2. **Dashboard** (8 files) — pure mirror of the engine API change: adds the two optional fields to the `HealthResponse` / `IBGatewayStatus` TypeScript shapes, and the two consuming UI surfaces (command-center IBKR badge + settings IBGatewayPanel) prefer `ibkr_execution_connected ?? ibkr_connected` so older engines still render correctly.
3. **Requirements pin** (`engine/requirements-core.txt`) — adds `xgboost==3.2.0` and a Windows note on `pandas-ta`'s `alligator.py` patch. Per memory `project_engine_boot_state_2026_05_04_eve`, both are already loaded in the running 5h+ venv.

All three groups are **ready-to-commit**. Nothing here looks WIP, experimental, or discardable.

## Proposed commit groupings

### Group 1 — Engine: split IBKR execution-vs-data connection state, surface blind-state on reconciliation

- **Files:**
  - `engine/api/models.py` (+3/-1)
  - `engine/routers/health_router.py` (+27/-4)
  - `engine/routers/brokers_router.py` (+53/-7)
- **Status:** ready-to-commit
- **Rationale:** Coherent change implementing memory's Recommendation A from `project_health_brokers_ibkr_divergence_2026_05_04`. `models.py` adds two new optional `HealthResponse` fields. `health_router.py` extracts an `_ib_is_connected()` helper that handles both attr and callable forms, computes `execution_connected` and `data_connected` independently, and surfaces both on `/health`. `brokers_router.py` threads `ibkr_connected`/`schwab_connected` into `_build_reconciliation()` and explicitly returns `health: "blind"` with an `all_brokers_disconnected` discrepancy when neither broker is queryable — directly fixing the "empty list looks clean but is silent failure" mode flagged in `project_tracker_broker_drift_2026_04_24`. Optional fields preserve wire compatibility. Engine has been running 5h+ without these changes loaded, so this is the first restart pickup; smoke after restart is prudent but the change itself is small and additive.
- **Suggested message:**
  ```
  feat(health): split ibkr_execution_connected vs ibkr_data_connected; surface blind-state on /brokers/positions

  - HealthResponse adds ibkr_execution_connected + ibkr_data_connected (optional, backward-compat)
  - _build_reconciliation now returns health: ok|partial|blind so an empty discrepancy
    list with both brokers offline cannot pass as a clean state (see project_tracker_broker_drift)
  - Snapshot connection state once per /brokers/positions request to avoid flap-during-request drift
  ```

### Group 2 — Dashboard: surface execution-connector state, fall back gracefully on older engines

- **Files:**
  - `dashboard/lib/api.ts` (+2/-0)
  - `dashboard/lib/settings-api.ts` (+2/-0)
  - `dashboard/components/EngineUptimeCard.tsx` (+2/-0)
  - `dashboard/components/SystemMetricsPanel.tsx` (+2/-0)
  - `dashboard/components/command-center/tabs/OverviewTab.tsx` (+2/-0)
  - `dashboard/components/command-center/tabs/SystemsTab.tsx` (+5/-2)
  - `dashboard/app/command-center/page.tsx` (+5/-2)
  - `dashboard/app/settings/page.tsx` (+5/-1)
- **Status:** ready-to-commit (paired with Group 1)
- **Rationale:** Mechanical mirror of the engine change. Six files only add the two optional fields to local `HealthResponse`/`HealthData`/`IBGatewayStatus` interfaces (no UI logic touched). Two files (`SystemsTab.tsx`, `app/command-center/page.tsx`, `app/settings/page.tsx`) update the IBKR badge / panel to prefer execution-connector state with `?? ibkr_connected` fallback for older engines, plus a `title=` tooltip explaining the behavior. No new components, no shape changes that would require a build/test — Next.js will type-check on next dev/build. Should ship together with Group 1 to keep the dashboard schema in sync.
- **Suggested message:**
  ```
  feat(dashboard): surface execution-connector IBKR state with fallback to legacy ibkr_connected

  - HealthResponse / IBGatewayStatus shapes gain optional ibkr_execution_connected + ibkr_data_connected
  - IBKR badge in command-center + IBGatewayPanel in /settings prefer execution-connector when present
  - Tooltip on each badge documents the fallback behavior for older engines
  ```

### Group 3 — Requirements: pin xgboost==3.2.0; document pandas-ta Windows patch

- **Files:**
  - `engine/requirements-core.txt` (+4/-1)
- **Status:** ready-to-commit
- **Rationale:** Adds `xgboost==3.2.0` (consumed by `engine/learning/model_drawer.py`) under a new `# ── ML / Predictions ──` header, and extends the `pandas-ta` comment to point at the Windows alligator.py patch documented in `project_engine_boot_state_2026_05_04_eve`. The package is already installed in the running engine venv (5h+ uptime per the same memory note), so this is purely declarative cleanup so a fresh `repair-engine-venv.ps1` rebuild reproduces the working state. Independent of Groups 1+2 — could ship before, after, or together.
- **Suggested message:**
  ```
  build(deps): pin xgboost==3.2.0 in requirements-core; document pandas-ta Windows patch

  xgboost is consumed by engine/learning/model_drawer; was loaded ad-hoc in the running venv but
  not in the bootstrap source. pandas-ta comment now references the alligator.py:6 patch needed on Windows
  (see project_engine_boot_state_2026_05_04_eve.md).
  ```

## Untracked

| Path | Size / Type | Recommendation |
|------|-------------|----------------|
| `docs/plans/2026-04-22-discord-bookmark-channel-backfill.md` | 8,806 lines, plan doc (Discord bookmark channel ingest) | **Commit.** Reference plan doc in `docs/plans/`, paired with the discord pipeline UTF-8 BOM fix in `project_discord_bookmarks_pipeline.md`. `docs:` commit. |
| `docs/plans/2026-04-25-mes-sprint-gate-design.md` | 104 lines, MES Sprint Gate design v1.0 | **Commit.** Companion to recent `feat(gate): MES Sprint Gate v1` commits already on the branch (`289b642`, `c862575`, `25e1ecf`, `8a6a029`, `104fc6d`). Capturing the design ex-post is the convention in `docs/plans/`. |
| `docs/plans/2026-04-25-mes-sprint-gate-implementation.md` | 603 lines, implementation plan with task-by-task steps | **Commit.** Same group as the design doc — both belong to the same `docs(plans):` commit. |
| `docs/session-logs/weekly-review-2026-04-26.md` | 225 lines, automated Sunday weekly review (Apr 20–26) | **Commit.** `docs(session-logs):` — matches the path/naming convention of every session log already tracked in `docs/session-logs/`. |
| `engine/.venv.broken-1777856098/` | ~37,466 files / 390 site-packages / pyvenv.cfg dated Mar 28 — typical 1.5–3 GB venv | **DELETE (do not commit).** Quarantined broken venv from 2026-05-02 repair attempt; replaced by `engine/.venv` which is now 5h+ stable. Only `.venv/` (no suffix) is in `.gitignore`, so this dir is currently *exposed* to git — deletion is required before this repo is ever pushed clean. Suggested: `Remove-Item -Recurse -Force engine\.venv.broken-1777856098`. Also worth proposing a `.gitignore` rule like `engine/.venv*/` to catch any future quarantined venvs. |
| `engine/data/morning_briefs/` | 1 file (`2026-04-27.md`, 780 bytes) | **Add to `.gitignore`** then leave on disk. The existing `.gitignore` excludes `engine/data/*.json` and the various RL/db/backup dirs, but morning briefs (auto-generated `.md` files) aren't covered. The `2026-04-27.md` file is auto-generated content (pre-market brief from the 07:00 CDT cron — see file body), not authored intent — same class as `paper_trades.json`. Recommend adding `engine/data/morning_briefs/` to `.gitignore` rather than committing the artifact. |

### Suggested untracked-doc commit

```
docs(plans): add Discord bookmark backfill + MES Sprint Gate design/implementation plans + weekly review

- 2026-04-22-discord-bookmark-channel-backfill.md — channel 1490851279180660819 ingest pipeline
- 2026-04-25-mes-sprint-gate-design.md — Sprint Gate v1.0 (lighter than Gate v2 for MES path-to-live)
- 2026-04-25-mes-sprint-gate-implementation.md — task plan (executed via 289b642, c862575, 25e1ecf,
  8a6a029, 104fc6d on this branch)
- weekly-review-2026-04-26.md — automated Sunday weekly review (Apr 20–26)
```

## Discard candidates

None among the modified files. All 12 are intentional, narrowly-scoped, and already match committed-branch conventions.

The only outright deletion candidate is the **`engine/.venv.broken-1777856098/`** directory (untracked, see table above) — this is filesystem cruft from the 2026-05-02 repair attempt, not a working tree change.

## Open questions for Amo

1. **Restart engine after Group 1+2 commits?** The engine has been running 5h+ on the pre-change code path. The new `ibkr_execution_connected`/`ibkr_data_connected` fields will only populate in `/health` after a `restart_engine.ps1` (no `--reload`, per the workflow rule). Recommended sequence: commit Group 1, commit Group 2, restart engine, verify `/health` exposes both fields, verify `/brokers/positions` returns `health: "ok"|"partial"|"blind"`.
2. **Group 3 (xgboost pin) ordering** — does it ship as a standalone commit before Groups 1+2, or bundled? The change is fully orthogonal; my recommendation is to ship it independently first (smallest, lowest-risk landing), then Groups 1 and 2 together.
3. **Untracked `engine/data/morning_briefs/`** — confirm the `.gitignore` addition (`engine/data/morning_briefs/`) rather than committing `2026-04-27.md`. The file is clearly auto-generated; treating it as gitignored output matches how `paper_trades.json` and `engine/data/*.db` are handled.
4. **Broken venv deletion** — confirm `Remove-Item -Recurse -Force engine\.venv.broken-1777856098`. ~37k files; will take a moment. No data inside (it's an installed-package mirror, all reproducible from `requirements-core.txt`). Also propose adding `engine/.venv*/` to `.gitignore` so any future quarantined venvs don't re-leak.
5. **Push to origin?** Branch is 43 ahead / 67 behind origin. The 67 behind is likely stale upstream history from a peer or rebase target — not in scope for this triage, but worth confirming intent before any push of these new commits.
