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

- **haiku** → Explore agents (file search, codebase orientation, quick lookups)
- **sonnet** → Implementation agents (writing code, fixing bugs)
- **opus** → Planning + safety review (architectural decisions, Tier 3 approvals)

## Constraint: No Background Agents

`run_in_background=true` fails on this machine (ENOTFOUND). Always use foreground agents.
Deploy up to 10 foreground agents for parallel work — replace any that stop.
