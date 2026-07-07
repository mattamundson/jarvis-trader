param(
    [string]$RepoPath = (Get-Location).Path,
    [string]$OutputPath = "HANDOFF_OpenAI_SESSION.md"
)

$ErrorActionPreference = "Stop"

function Get-GitOutput {
    param([string]$Command)
    try {
        return (Invoke-Expression $Command | Out-String).TrimEnd()
    }
    catch {
        return "ERROR running: $Command`n$($_.Exception.Message)"
    }
}

if (-not (Test-Path $RepoPath)) {
    throw "RepoPath does not exist: $RepoPath"
}

Set-Location $RepoPath

$gitStatus = Get-GitOutput "git status"
$gitLog = Get-GitOutput "git log --oneline -20"
$gitDiffStat = Get-GitOutput "git diff --stat"
$branch = Get-GitOutput "git rev-parse --abbrev-ref HEAD"
$timestamp = (Get-Date).ToString("s")

$content = @"
# HANDOFF_OpenAI_SESSION

Generated: $timestamp
Repo root: $RepoPath
Branch: $branch

## 1) Session summary — what was accomplished, in what order

> FILL THIS IN WITH THE ACTUAL SESSION WORK. Do not leave vague. Use chronology.

## 2) Files created or modified — full paths, what changed, why

| Full path | Created / Modified | What changed | Why |
|---|---|---|---|
| `REPLACE_ME` | Modified | REPLACE_ME | REPLACE_ME |

## 3) Current state — what's running, what's stopped, what's broken

### Running
- REPLACE_ME

### Stopped
- REPLACE_ME

### Broken / degraded
- REPLACE_ME

## 4) In-progress work — anything started but not finished

- REPLACE_ME

## 5) Blockers discovered — issues found that need resolution

- REPLACE_ME

## 6) Key decisions made — architectural choices, parameter values, tradeoffs

- REPLACE_ME

## 7) TODO items — what was planned but not started

- REPLACE_ME

## 8) The full to-do list you currently have

- [TODO] REPLACE_ME
- [IN_PROGRESS] REPLACE_ME
- [BLOCKED] REPLACE_ME
- [DONE] REPLACE_ME

## 9) Git state — include full command output

### `git status`

```text
$gitStatus
```

### `git log --oneline -20`

```text
$gitLog
```

### `git diff --stat`

```text
$gitDiffStat
```

## Additional operational context

### Environment
- OS: Windows
- Repo root: $RepoPath
- Branch: $branch
- Generated: $timestamp

### How to resume work
1. Read this file fully.
2. Review `NEXT_STEPS.md`.
3. Review `SESSION_STATE.json`.
4. Reconcile all three documents against the actual repo.
5. Continue from the highest-priority unfinished task.
"@

Set-Content -Path $OutputPath -Value $content -Encoding UTF8
Write-Host "Generated handoff at $OutputPath"
