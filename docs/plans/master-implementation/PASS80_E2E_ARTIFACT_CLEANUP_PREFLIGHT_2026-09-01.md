# PASS80 - E2E Artifact Cleanup Preflight

## Scope

Completed P16-011 and P16-012 without removing files.

## Changes

- Added `scripts/inspect-jarvis-e2e-artifacts.ps1`.
- The script defaults to dry run.
- The script validates the exact expected root:
  `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts`
- The script operates only on child directories under that root.
- The script refuses `-Execute` unless `-ConfirmApprovedGeneratedArtifactCleanup` is also present.

## Dry-Run Evidence

```powershell
.\scripts\inspect-jarvis-e2e-artifacts.ps1
```

Result:

- Mode: `DRY RUN`
- Child directories: `97`
- Artifact size: `19.46 GB`
- C: free before: about `0.92 GB`
- Largest child directories are isolated Next build outputs around `0.40 GB` each.

## Guard Evidence

```powershell
try {
  & .\scripts\inspect-jarvis-e2e-artifacts.ps1 -Execute
  Write-Host 'unexpected execute success'
  exit 1
} catch {
  Write-Host "guard ok: $($_.Exception.Message)"
  exit 0
}
```

Result:

- The command exited successfully from the catch branch.
- Guard message: `Execution requires -ConfirmApprovedGeneratedArtifactCleanup after explicit approval.`
- Follow-up size/count check still showed `97` directories and `19.46 GB`.

## Remaining Gate

[RISK] Actual cleanup is still blocked until Amo explicitly approves removing the historical generated artifact child directories.
