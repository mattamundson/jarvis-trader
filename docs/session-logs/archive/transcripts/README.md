# Cursor agent transcripts (archived copies)

This directory holds **copies** of Cursor IDE agent transcript JSONL files for the JARVIS Trader workspace. The live files are updated by Cursor under:

`C:\Users\mattm\.cursor\projects\c-Users-mattm-ThinkorSwim-jarvis-trader-jarvis-trader-code-workspace\agent-transcripts\`

## Why these exist

Session logs under `docs/session-logs/*.md` are curated narratives. The JSONL files are the closest **verbatim** record of user/assistant turns (plus tool metadata) for a given parent chat UUID.

## Refreshing a copy

From PowerShell (adjust UUID folder if Cursor creates a new parent id):

```powershell
$src = "$env:USERPROFILE\.cursor\projects\c-Users-mattm-ThinkorSwim-jarvis-trader-jarvis-trader-code-workspace\agent-transcripts\0e951585-2622-4dad-8e88-e6dd89a4f98b"
$dst = "docs\session-logs\transcripts\0e951585-2622-4dad-8e88-e6dd89a4f98b"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Path (Join-Path $src "*.jsonl") -Destination $dst -Force
Copy-Item -Path (Join-Path $src "subagents") -Destination (Join-Path $dst "subagents") -Recurse -Force
```

## Security

Transcripts can contain pasted secrets. Run your secret scanner (e.g. `detect-secrets` / `scripts/hooks/check-secrets.sh`) before committing. Do not commit live API keys.

## Subagents

Per Cursor rules, **do not cite subagent transcript IDs** in user-facing docs; only the **parent** UUID is the stable reference for the main conversation.
