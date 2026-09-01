# PASS72 - E2E Artifact Disk Recovery Path

## Scope

Completed P13-010 by recording the current disk blocker and the safe recovery path for historical isolated E2E artifacts.

## Current State

- `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts` contains 97 archived isolated build/test artifact directories.
- C: free space was below 1 GB after PASS70/PASS71 validation.
- The runner is now fixed for future successful runs, but historical artifact directories still consume substantial space.

## Recovery Path

[RISK] The historical artifact directory is larger than 1 GB, so cleanup requires explicit approval under the cleanup/archive rule even though these are reproducible temp build/test artifacts.

Recommended approved action:

```powershell
$target = 'C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts'
Get-ChildItem -LiteralPath $target -Directory | Remove-Item -Recurse -Force
```

This removes only generated isolated Next/Playwright artifacts. It does not touch source, repo files, handoffs, evidence docs, or project data.

## Non-Destructive Work Completed

- Future successful isolated E2E runs no longer add permanent artifact directories by default.
- Failed isolated E2E runs still keep evidence unless `JARVIS_E2E_ARTIFACT_MODE=never` is set.
