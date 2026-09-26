# Canonical Serving Tree — Preservation Inventory (2026-09-04)

Purpose: enumerate every deploy-only artifact a dashboard/engine cutover MUST carry over from `C:/Users/mattm/ThinkorSwim/jarvis-trader`. Captured read-only; secrets listed by presence/metadata only, never contents.

## Runtime secrets/config (single-writer locks — carry over, never commit)

| Artifact | Exists | Size | Last modified |
|---|---|---|---|
| `engine/.env` | yes | 19,983 B | 2026-09-02 22:29 |
| `dashboard/.env.local` | yes | 211 B | 2026-09-02 22:23 |

## Build/dependency artifacts (regenerable but expensive — prefer carry-over or rebuild-in-place)

| Artifact | Exists | Notes |
|---|---|---|
| `dashboard/.next/BUILD_ID` | yes | `XkrhceydxgJxDzVE`, built 2026-09-03 16:37 |
| `dashboard/node_modules` | yes | pnpm tree, 2026-09-02 22:17 |
| `engine/.venv` | yes | Windows venv, 2026-09-02 21:33 |

## Runtime truth artifacts

| Artifact | Exists | Notes |
|---|---|---|
| `phase0_runtime_truth_snapshot.json` | yes | 4,779 B, refreshed 2026-09-04 04:21 by scheduled task |
| `logs/phase0_runtime_truth_snapshot_refresh.log` | yes | refresh-task log |

## Supervision config

| Artifact | Exists | Notes |
|---|---|---|
| `dashboard/ecosystem.config.js` | yes | 741 B, absolute-path next binary |
| `engine/ecosystem.config.js` | yes | 19,915 B, port_guardian entry |
| `~/.pm2/dump.pm2` | yes | 32,856 B, saved 2026-09-04 04:19 |

## Scheduled-task scripts (re-register after cutover if paths change)

| Artifact | Exists |
|---|---|
| `scripts/refresh_phase0_runtime_snapshot.ps1` | yes |
| `scripts/install_phase0_runtime_snapshot_task.ps1` | yes |
| Windows task `Jarvis-A01-RuntimeSnapshotRefresh` | registered, 5-min repeat |

## Engine log directory (11 entries, carry-over for continuity)

`engine/logs/`: `engine-error.log`, `engine-out.log`, `engine.log`, `jarvis.log`, `nightly_discord.log`, `pytest.log`, `port_guardian_boot_times.jsonl`, `port_guardian_restarts.jsonl`, plus 2 rotated `__2026-09-04` logs and `deep_analyzer/`.

## Cutover carry-over rule

Any cutover must: (1) preserve both env files byte-for-byte, (2) preserve or rebuild `.next` before `next start`, (3) preserve `engine/.venv` or reinstall from `requirements-core.txt`, (4) re-register the snapshot refresh task if the canonical path changes, (5) `pm2 save` after supervision changes.
