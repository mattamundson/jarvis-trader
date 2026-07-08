# Second-Brain Vault — Operations Runbook

> Canonical reference for vault layout, gbrain ingest pipeline, session-stamped output dirs, and recovery procedures after the 2026-05-20 migration.

**Status**: Production (post-migration, 2026-05-20)
**Scheduled task**: `Jarvis-VaultGbrainSync` (30-min cron)
**Extraction script**: `scripts/extract_discord_to_vault.py` (commit `d977ee8`)
**Enrichment script**: `scripts/enrich_discord_bookmarks.py` (commit `d7c3909`)

---

## Overview

Matt's second-brain is a multi-vault Obsidian setup. The canonical ingested vault is at `C:\Users\mattm\master-jarvis\second-brain\`. Every 30 minutes the Windows scheduled task `Jarvis-VaultGbrainSync` pushes changes into the gbrain trading brain, which the JARVIS engine uses for semantic search over Discord commentary, bot signals, and curated wiki pages.

Two secondary vault roots exist but are **not** watched by the sync task (see Vault Root section below). Do not confuse them with the canonical root.

---

## Vault Root Canonicalization (critical)

Three vault roots co-exist on this machine. Only one is ingested.

| Root | Status | Purpose |
|------|--------|---------|
| `C:\Users\mattm\master-jarvis\second-brain\` | **Canonical — ingested** | All new writes go here; `Jarvis-VaultGbrainSync` watches this path |
| `C:\Users\mattm\second-brain\` | **Archived 2026-07-07 — GONE** | Empty 25-file remnant moved to `~/Archive/2026/second-brain-vault-a/` after the 2026-05-29 merge into the canonical root. Any code still pointing here now hits an absent path (see Known Issues). |
| `C:\Users\mattm\my-vault\` | Separate Obsidian vault — NOT ingested | Distinct purpose; not part of the trading brain pipeline |

**Rule:** all new vault writes from any session must target `master-jarvis/second-brain/raw/`. A naive `Glob ~/second-brain/` hits the legacy root and finds nothing recent — always qualify the full path.

---

## Directory Layout

```
master-jarvis/second-brain/raw/
├── wiki/                        # Peer session consolidated wiki (3,374 files as of 2026-05-20)
├── x-bookmarks/                 # Historical X.com bookmarks, one file each
├── files/                       # Attachments and binary imports
├── logs/                        # Ingest process logs
├── trading/                     # Trading-specific structured notes
├── assets/                      # Images, PDFs, media
├── clippings/                   # Web clippings
├── archive/                     # Rotated/retired vault files (recovery source)
├── _ingest-status.md            # Live sync diagnostics (~67 MB as of 2026-05-20 17:00, actively appended)
├── _ingest-stale.md             # Files flagged stale by gbrain
└── _session-2026-05-20-amo/     # Namespaced subdir for the 2026-05-20 dispatch (4,581 files)
```

### Session-Stamped Subdirectory (`_session-2026-05-20-amo/`)

Output of the 2026-05-20 multi-agent Discord extraction dispatch:

| Subdirectory | File count | Source |
|---|---|---|
| `discord-bookmarks/` | 1,018 | Raw extraction of channel `1490851279180660819` |
| `discord-commentary/` | 1,042 | Daily aggregates from `discord_corey_commentary` table |
| `discord-analyses/` | 1,055 | LLM analyses of commentary |
| `discord-ib-reports/` | 1,000 | `discord_ib_reports` table |
| `discord-bot-signals/` | 251 | Monthly per-symbol aggregates from 221K rows |
| `discord-corey-alerts/` | 68 | Alert extracts |
| `discord-daily-sentiment/` | 63 | Monthly sentiment aggregates |
| `discord-attachments/` | 0 | `attachment_urls` column was unpopulated — expected empty |
| `wiki/` | 84 | System / trading / concepts / authors / repos pages |

---

## Scheduled Ingest — `Jarvis-VaultGbrainSync`

**Schedule**: every 30 minutes
**Watches**: `master-jarvis/second-brain/raw/` only

### Check task status

```powershell
schtasks /Query /TN "Jarvis-VaultGbrainSync" /V /FO LIST
```

Pass criteria:
- `Status: Ready`
- `Next Run Time:` shows a plausible near-future timestamp (not `N/A`)

### Trigger ingest manually

```powershell
schtasks /Run /TN "Jarvis-VaultGbrainSync"
```

Wait ~60 seconds, then verify:

```powershell
# Check the ingest status file for a new run entry
# (tail the last few lines via PowerShell)
Get-Content "C:\Users\mattm\master-jarvis\second-brain\raw\_ingest-status.md" -Tail 20
```

A successful run appends a timestamped entry with chunk counts. No new entry after 90 seconds indicates the task did not fire — see Troubleshooting below.

---

## Extraction Script

**Path**: `scripts/extract_discord_to_vault.py`
**Commit**: `d977ee8`
**Run from project root**:

```powershell
engine\.venv\Scripts\python scripts\extract_discord_to_vault.py
```

Key behaviors:
- Idempotent — uses `message_id` for dedup; re-running on the same data is safe
- Default output path is `~/second-brain/raw/` (the legacy root) — see Known Issues

**Post-run migration step (required until path-config is fixed):**

After extraction, robocopy the output to the canonical root under a session-stamped subdir:

```powershell
robocopy "C:\Users\mattm\second-brain\raw" `
         "C:\Users\mattm\master-jarvis\second-brain\raw\_session-<DATE>-amo" `
         /E /COPY:DAT /MT:8
```

Then trigger the sync task manually to ingest the new files.

---

## Enrichment Script

**Path**: `scripts/enrich_discord_bookmarks.py`
**Commit**: `d7c3909`
**Run from project root**:

```powershell
engine\.venv\Scripts\python scripts\enrich_discord_bookmarks.py
```

Key behaviors:
- Adds a `## Cross-links` section to each raw bookmark file
- Wikilinks inserted: `[[author]]`, `[[repos/...]]`, `[[theme]]`, `[[master-index]]`, `[[discord-jarvis-mcp]]`
- Idempotent via `<!-- ENRICHED:CROSS-LINKS -->` marker — files already enriched are skipped
- Operates on files at their path at script-write time; if files were moved after enrichment, re-running on the new location is a no-op (marker is already in place)

---

## Peer-Session Coordination

Two sessions wrote vault content concurrently on 2026-05-20, handled via namespaced subdirs. Follow this pattern in all future sessions.

**At session start:**

```powershell
# See what prior sessions have written
Get-ChildItem "C:\Users\mattm\master-jarvis\second-brain\raw" -Filter "_session-*" -Directory
```

- If continuing an existing session's work, write into that session's subdir
- If starting fresh work, create a new `_session-<YYYY-MM-DD>-<owner>/` subdir
- Do NOT write directly into `raw/wiki/` without checking for collisions with peer session `_INDEX.md` and numbered agent reports

**Check for active peer sessions:**

```powershell
bash ~/.claude/hooks/session_manifest.sh list
```

See `rules/session_coordination.md` for the full coordination protocol.

---

## OneNote Ingest — `Jarvis-VaultIngest-OneNote`

**Schedule**: monthly, 1st @ 03:30 CT
**Script**: `C:\Users\mattm\master-jarvis\scripts\ingest\onenote-ingest.ps1`
**Task working directory**: `C:\onx` (set 2026-05-21 — required so exporter finds `Resources\trad.en.json`)
**Exporter**: `C:\onx\OneNoteMdExporter.exe` v1.6.0 (COM-based, requires OneNote desktop)

### Root cause of exit -532462766 (0xE0434352)

The exporter crashes with a .NET CLR unhandled exception when OneNote's COM RPC server
drops mid-export. This happens in unattended/scheduled context when the `AmoSZN` notebook's
large `Quick Notes` section (1170+ pages) causes cascading RPC failures (0x800706BE/0x800706BA).

**Fixed (2026-05-21)**:
- Task `Start In` set to `C:\onx` so exporter always finds `Resources\trad.en.json`
- Script updated to treat exit -532462766 as partial success when exported files exist: merge
  proceeds with whatever pages were exported before the crash
- 984 existing OneNote pages committed to `second-brain/raw/onenote/` in the correct
  canonical vault path; gbrain ingested 558 new chunks (large sync, 2026-05-21)

### Remaining credential issue (unresolved — Amo action required)

**[RISK] Plaintext OpenAI admin key** found in:
```
raw/onenote/Matt's Notebook (2)/New Section 29/I need to create an AI agent that can communicate .md
raw/onenote/Matt's Notebook (2)/New Section 29/QUARANTINED-page-1777955898-28487.md
```
These 2 files were NOT committed to git (pre-commit hook blocked). Action:
1. Rotate the `sk-admin-trR5bsSfnuW2PR6YtEmjZAnUF-...` key at https://platform.openai.com/api-keys
2. After rotation, redact the old key value in the two files (replace with `[ROTATED-OPENAI-ADMIN-KEY]`)
3. Then `git add "raw/onenote/Matt's Notebook (2)/New Section 29/"` and commit

**Also excluded (4 total files)**: Two `Trading Notes/The Mouthbreather's Guide to the Galaxy*.md`
files contain satirical `sk-` patterns (fictional stock-ticker jokes, not real keys). These
are also not committed. Review manually and commit once confirmed non-secret.

### Ongoing limitation

The `AmoSZN` notebook (1170+ pages, mostly GMS/personal content) consistently crashes the
exporter at around page 55-60 of the `Quick Notes` section. With `--ignore-errors` the
exporter continues page-by-page, but the COM session degrades and eventually dies. The
partial-success fix ensures exported content before the crash is still merged.

---

## Known Issues and Open Follow-ups

| Issue | Impact | Resolution |
|-------|--------|------------|
| ~~`extract_discord_to_vault.py` writes to `~/second-brain/raw/` by default~~ | FIXED 2026-07-07 | `DEFAULT_VAULT_RAW` now targets `master-jarvis/second-brain/raw/` (the canonical ingested root). The `--output-path` flag still overrides for session-dated subdirs (`_session-<DATE>-amo/`). |
| ~~Bookmark scripts hardcode the archived legacy root~~ | FIXED 2026-07-07 | `enrich_discord_bookmarks.py` (read dir) repointed `second-brain\raw\discord-bookmarks` → `master-jarvis\second-brain\raw\discord-bookmarks` (subpath preserved). `render_bookmarks_to_vault.py` (write default) repointed to `master-jarvis\second-brain\raw\wiki\discord-bookmarks` — note the added `raw\` segment: the old Vault A default (`second-brain\wiki\...`, no `raw\`) was carried over uncorrected in the first pass, which would have written outside the tree `Jarvis-VaultGbrainSync` watches (`raw/` only, §"Vault Root Canonicalization" above); caught by review and fixed before merge. `engine/main.py` already derives its bookmark dir from `vault_root()`/`JARVIS_VAULT_ROOT` — no change needed. |
| PowerShell scan/cleanup scripts still list the archived root | Low — they scan a now-absent path; harmless no-op/error | `archive-rotate.ps1`, `scan-uncommitted.ps1`, `repo-remote-check.ps1` list `C:\Users\mattm\second-brain` as a scan target; `phase0-cleanup.ps1` tracks an OneNote path under it. Left for a workstation-verified pass — behavior can't be exercised from a Linux CI clone, so drop the entry only after confirming each script's intent locally. |
| `Jarvis-VaultGbrainSync` watches only `master-jarvis/second-brain/` | Content in `~/second-brain/raw/inbox/` is never auto-ingested | Consider extending the task if that dir becomes a working ingest area |
| Enrichment marker is location-bound | Moving files post-enrichment leaves cross-links in the old location | Re-enrich at the destination if files are relocated after enrichment |
| OneNote `New Section 29` files with plaintext OpenAI admin key | 2 files excluded from git, not in gbrain | Rotate key at platform.openai.com, then redact and commit (see OneNote section above) |
| OneNote `AmoSZN` notebook crashes exporter at ~page 55/1170 | AmoSZN content not exported; only Matt's Notebook (984 pages) is indexed | Partial-success fix in place; AmoSZN content requires interactive OneNote session to export cleanly |

---

## Troubleshooting

### gbrain ingest appears stuck

```powershell
# Kill and re-trigger
schtasks /End /TN "Jarvis-VaultGbrainSync"
Remove-Item "C:\Users\mattm\master-jarvis\second-brain\raw\_ingest-status.md"
schtasks /Run /TN "Jarvis-VaultGbrainSync"
```

### Vault file accidentally deleted

Restore from `master-jarvis/second-brain/raw/archive/` — gbrain auto-rotates retired files there. If not present in archive, check the session-stamped subdir from the originating dispatch.

### Scheduled task shows `Status: Disabled` or `Next Run Time: N/A`

```powershell
schtasks /Change /TN "Jarvis-VaultGbrainSync" /ENABLE
```

If re-enabling fails with an access error, re-register the task via `install-regression-tasks.ps1` or the original task-install script.

### Peer session file collision

Check `~/.claude/session_manifest.json` for active peers. If two sessions are both writing to the same subdir, coordinate by having one session pause writes until the other finishes its batch, or split by subdirectory ownership. See `rules/session_coordination.md`.

### `_ingest-status.md` growing beyond 100 MB

Truncate the oldest entries:

```powershell
# Keep last 500 lines
Get-Content "C:\Users\mattm\master-jarvis\second-brain\raw\_ingest-status.md" -Tail 500 |
    Set-Content "C:\Users\mattm\master-jarvis\second-brain\raw\_ingest-status.md"
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Check sync task status | `schtasks /Query /TN Jarvis-VaultGbrainSync /V /FO LIST` |
| Trigger ingest now | `schtasks /Run /TN "Jarvis-VaultGbrainSync"` |
| Run extraction | `engine\.venv\Scripts\python scripts\extract_discord_to_vault.py` |
| Run enrichment | `engine\.venv\Scripts\python scripts\enrich_discord_bookmarks.py` |
| List session output dirs | `Get-ChildItem master-jarvis\second-brain\raw -Filter "_session-*" -Directory` |
| Check peer sessions | `bash ~/.claude/hooks/session_manifest.sh list` |
| Check ingest log tail | `Get-Content master-jarvis\second-brain\raw\_ingest-status.md -Tail 20` |

---

## Related Runbooks

- `[[DISCORD_INTEL_RUNBOOK]]` — Discord data extraction, Supabase schema, channel IDs
- `[[CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP]]` — Hermes gateway, MCP wiring, Discord bot signals
- `[[DAILY_AUTOMATION]]` — Scheduled tasks overview, PM2 processes, cron schedule
