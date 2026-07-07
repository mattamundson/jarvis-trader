# Obsidian Second-Brain — Vault A retired, loop writers repointed to Vault B

**Decision date:** 2026-07-07
**Resolves:** Open item from `MEMORY/project_second_brain_vault_a_not_dupe_2026_05_29`
(archive Vault A) + a latent orphaned-digests bug surfaced while resolving it.
**Status:** DONE — executed on the workstation, recorded here for repo history.

## Context

Two directories named `second-brain` existed on the workstation:

| Alias | Path | Role |
|---|---|---|
| Vault A | `C:\Users\mattm\second-brain` | Home-root remnant. 25 files at time of retirement. NOT served by the Obsidian MCP, NOT ingested by gbrain. |
| Vault B | `C:\Users\mattm\master-jarvis\second-brain` | Canonical vault. ~57k notes. Served by the Obsidian MCP, in the graph. |

Vault A's unique wiki content had already been merged into Vault B on 2026-05-29
(`Vault B\wiki\_vault-a-merge-2026-05-29\`, 805 files confirmed present). The only
remaining open item from that merge was archiving the Vault A shell — explicitly
left as an Amo-gated next step.

## Bug surfaced while resolving it

Vault A was not actually stray. Four scheduled loop runners hardcoded it as their
write target — so every daily digest since ~2026-07-02 was landing in a vault the
Obsidian MCP does not serve and gbrain does not ingest (i.e. invisible in Obsidian
and absent from the graph). Each runner also `New-Item -Force`s the directory back
if missing, so a bare archive would have silently respawned it.

| Loop runner | Line | Old target (Vault A) |
|---|---|---|
| `~/.claude/loops/overnight-orchestrator/run.ps1` | 37 | `second-brain\Notes\overnight-orchestrator` |
| `~/.claude/loops/loop-error-miner/run.ps1` | 34 | `second-brain\Notes\loop-error-miner` |
| `~/.claude/loops/hermes-analyst/run.ps1` | 32 | `second-brain\Notes\hermes-analyst` |
| `~/.claude/loops/hermes-implementer/run.ps1` | 35 | `second-brain\Notes\hermes-analyst` |

(`phase0-cleanup.ps1` / `archive-rotate.ps1` also reference Vault A but read-only —
cleanup/scan targets, not writers. Left untouched.)

## Decision & actions taken

1. **Repointed** all four `$vaultDir` lines from `second-brain\Notes\...` to
   `master-jarvis\second-brain\Notes\...` (Vault A → Vault B). Takes effect on each
   loop's next scheduled fire; scheduled tasks re-read the script every run, so no
   restart needed.
2. **Merged** all 25 remaining Vault A files into the matching Vault B folders,
   collision-safe (skip-if-exists). Zero collisions. Verified readable in B:
   overnight-orchestrator (5 digests), loop-error-miner (3 reports),
   hermes-analyst (6), 4 connection-graph SVGs, 3 X-Bookmarks (coexist with B's
   existing 3), plus raw scan logs.
3. **Archived** the now-empty Vault A shell to
   `C:\Users\mattm\Archive\2026\second-brain-vault-a\` via `robocopy /MOVE`
   (reversible; directory structure preserved) and removed the home-root
   `C:\Users\mattm\second-brain`. Confirmed gone.

## Lesson

Before archiving a directory that "looks stray," grep the loop/task runners for its
path — a near-empty directory can still be an active, mis-targeted write destination.
The emptiness was the symptom, not evidence of disuse.

## References

- Prior merge decision: `MEMORY/project_second_brain_vault_a_not_dupe_2026_05_29`
- Canonical vault (Vault B): `C:\Users\mattm\master-jarvis\second-brain`
- Archive location: `C:\Users\mattm\Archive\2026\second-brain-vault-a\`
