# jarvis-trader handoff bundle

This bundle was created because the ChatGPT execution environment did **not** have access to:

- `C:\Users\mattm\ThinkorSwim\jarvis-trader`
- the actual `jarvis-trader` git repository
- the project files needed for a true repo-grounded handoff

What this bundle gives you:

1. `HANDOFF_OpenAI_SESSION_TEMPLATE.md`
   - Repo-aware handoff template with all required sections.
2. `NEXT_STEPS.md`
   - Human-readable prioritized next-steps template.
3. `SESSION_STATE.json`
   - Machine-readable AI continuity file.
4. `generate_handoff.ps1`
   - PowerShell script to generate a real handoff file inside the repo and append live git outputs.
5. `NEXT_AI_PROMPT.md`
   - Prompt to give the next AI session once the repo is available.
6. `CURRENT_SESSION_HANDBACK.md`
   - Copy of the current environment-limited handoff for reference.

## Recommended use

### Step 1 — copy files into the repo root
Copy all files from this bundle into:

`C:\Users\mattm\ThinkorSwim\jarvis-trader\`

### Step 2 — generate a real repo handoff
Open PowerShell in the repo root and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\generate_handoff.ps1
```

That script will:
- detect the repo root
- collect:
  - `git status`
  - `git log --oneline -20`
  - `git diff --stat`
- create/overwrite:
  - `HANDOFF_OpenAI_SESSION.md`

### Step 3 — review and fill placeholders
Because only you / the next AI session will know the actual architectural details, manually or with AI fill in any placeholders around:
- session summary
- exact file modifications
- current runtime state
- blockers
- decisions
- in-progress work
- TODOs

### Step 4 — give the repo to the next AI session
Provide the next session with:
- the repo/folder mounted or uploaded
- `HANDOFF_OpenAI_SESSION.md`
- `NEXT_STEPS.md`
- `SESSION_STATE.json`
- `NEXT_AI_PROMPT.md`

## Important limitation

The original `HANDOFF_OpenAI_SESSION.md` created in this ChatGPT session reflects **this conversation only** and not the real repo state. Use it only as a reference artifact, not as the authoritative project handoff.
