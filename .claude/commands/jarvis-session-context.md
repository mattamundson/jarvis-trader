---
description: Dump the current jarvis-trader session context — git status, last commit, engine health, active positions, last WhatsApp approval, recent session logs. Use at session start to re-prime or before /compact.
allowed-tools: Bash(git:*), Bash(curl:*), Read, Glob
argument-hint: "(no arguments)"
---

# Session Context Dump

Re-prime context without manually querying five things. Runs in parallel where safe.

## Steps

Run these Bash calls in a single message (parallel):

1. **Git state**:
   ```bash
   cd "C:/Users/mattm/ThinkorSwim/jarvis-trader" && git -c color.ui=false status --short | head -30
   cd "C:/Users/mattm/ThinkorSwim/jarvis-trader" && git log --oneline -5
   ```

2. **Engine health**:
   ```bash
   curl -s http://localhost:8010/health | head -c 400
   ```

3. **Current paper positions** (if engine up):
   ```bash
   API_KEY="${JARVIS_API_KEY}"
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/portfolio/paper/positions | head -c 1000
   ```

4. **Latest session log** (Glob then Read the newest one):
   ```
   Glob: C:/Users/mattm/ThinkorSwim/jarvis-trader/docs/session-logs/handoff-*.md
   Read: only the top 40 lines of the newest match (handoffs are YAML frontmatter first)
   ```

## Output format

```
## Session Context — <date> <time>

### Git
- Branch: <branch>
- Uncommitted: <n> files (top 5: ...)
- HEAD: <hash> — <subject>

### Engine
- Status: <healthy|degraded|down>
- If down: <error summary>

### Positions
- Open: <n> (<symbol list>)
- Or: "no open positions"

### Last handoff
- File: <path>
- Date: <from frontmatter>
- Status: <from frontmatter>
- Next actions (first 3 bullets): ...
```

## Constraints

- Read-only. Do not `git add`, do not pull, do not push.
- If the newest handoff is older than 48h, flag `stale session log — consider writing a new handoff before /compact`.
- If engine is down, still emit the git + handoff sections — partial context is better than nothing.

## Why this exists

Pattern source: `goldentrii/agentrecall` `/arstart` command + `thedotmack/claude-mem` cross-session reload pattern. Matt has `jarvis-trader/docs/session-logs/handoff-*.md` but no slash invocation that pulls handoff + git + engine in one shot — forcing manual re-priming each session.
