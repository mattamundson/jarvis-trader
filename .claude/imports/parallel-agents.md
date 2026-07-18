# Parallel Agent Protocol — Atomic Task Checkout

When running multiple Claude Code agents in parallel, use the task manifest to prevent file conflicts.

## Protocol

1. **At session start**: Read `.claude/task-manifest.json`
2. **Claim your task**: Set `status: "in_progress"` and `owner: "your-session-id"`
3. **Never edit a file owned by another session**
4. **On completion**: Set `status: "done"`, `owner: null`

Task manifest: `.claude/task-manifest.json` (20 tasks mapped to real engine files)

## Reset Before Multi-Agent Session

```bash
python3 -c "
import json
with open('.claude/task-manifest.json') as f: m = json.load(f)
for t in m['tasks']: t['status'] = 'unowned'; t['owner'] = None
with open('.claude/task-manifest.json', 'w') as f: json.dump(m, f, indent=2)
print('Manifest reset')
"
```

## Model Tiering for Agents

Route by task complexity, not by default. Real model IDs in parentheses.

- **haiku** (`claude-haiku-4-5`) → Explore + grader agents (file search, codebase
  orientation, quick lookups, and independent verifier/grader passes — a fresh
  context that checks another agent's output beats self-critique)
- **sonnet** (`claude-sonnet-5`) → Implementation agents (writing code, fixing bugs)
- **opus** (`claude-opus-4-8`) → Planning + safety review (architectural
  decisions, Tier 3 approvals); also the fallback when Fable declines a domain
- **fable** (`claude-fable-5`) → Orchestrator role for long, multi-stage runs
  that plan across sub-agents and distill results. Reserve for work that earns
  the top-tier cost; delegate bounded subtasks down-tier.

## Worktree Isolation for Parallel Writers

When more than one agent writes files concurrently, give each its own checkout so
edits cannot collide: set `isolation: "worktree"` on the subagent, or run it in a
dedicated `git worktree`. Read-only Explore/grader agents do not need this. It
complements the task-manifest checkout above — the manifest prevents two sessions
*claiming* the same task; worktrees prevent *file-level* collisions during the work.

## Constraint: No Background Agents

`run_in_background=true` fails on this machine (ENOTFOUND). Always use foreground agents.
Deploy up to 10 foreground agents for parallel work — replace any that stop.
