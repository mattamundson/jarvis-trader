# JARVIS TRADER — Ralph Loop Protocol

JARVIS runs 5 parallel Claude Code agents using the `/ralph` autonomous development loop.
This is the project instruction: **"Deploy 5 agents to work in parallel. If an agent stops,
start another. Ensure 5 agents are working tirelessly until the project is complete across
sessions and time. Utilize /ralph loop for all 5 agents."**

---

## The 5 Agents — Current State

Each agent owns a dedicated PRD file and branch. They work in parallel without file conflicts
by owning separate areas of the codebase.

| Agent | PRD File | Branch | Area | Done |
|---|---|---|---|---|
| Agent 1 | `scripts/ralph/prd-agent1-commit-triage.json` | `ralph/commit-triage` | Commit triage, repo foundation, SQLite MCP | 0/11 |
| Agent 2 | `scripts/ralph/prd-agent2-mes-revalidation.json` | `ralph/mes-revalidation` | MES re-validation, RL Run 10 WFE | 5/7 |
| Agent 3 | `scripts/ralph/prd-agent3-correlation-monitoring.json` | `ralph/correlation-monitoring` | Portfolio correlation monitoring, risk endpoint | 0/6 |
| Agent 4 | `scripts/ralph/prd-agent4-dashboard.json` | `ralph/three-instrument-dashboard` | Dashboard: validation scorecard, P&L chart, correlation UI | 1/6 |
| Agent 5 | `scripts/ralph/prd-agent5-learning-system.json` | `ralph/learning-system-wiring` | Learning system wiring: trade-close → feedback → patterns → pipeline | 0/7 |

**Agent 2 is closest to done** — 2 stories remain. Start here when spinning up a new session.

---

## How to Start a Ralph Session

### Starting any agent

```
1. Open a new Claude Code session in jarvis-trader/
2. Say: "Run ralph for Agent N" (where N = 1–5)
3. Claude reads the PRD file, checks progress, picks the highest-priority incomplete story
4. Works ONE story per response
5. Commits: feat: [US-ID] - Story Title
6. Updates prd.json: passes: true
7. Appends learnings to progress file
8. Ends response — next session picks up the next story
```

### Critical: Always check task manifest first

Before starting work, claim your task in `.claude/task-manifest.json` to avoid
file conflicts with other agents:

```python
# Read the manifest
import json
with open('.claude/task-manifest.json') as f:
    manifest = json.load(f)

# Find an unowned task for your agent area
# Set status: "in_progress", owner: "agent-N-session-id"
# Save back before touching any files
```

### One story per session

Ralph does ONE story per response. Do not attempt multiple stories in one session.
This keeps commits focused and allows parallel agents to work without conflicts.

---

## Agent Ownership Map (File Boundaries)

Agents must not edit files owned by other agents. This table is the authority.

| Agent | Owns / Primarily Edits |
|---|---|
| Agent 1 | `.claude/`, `scripts/`, `CLAUDE.md`, root config files, git/submodule setup |
| Agent 2 | `engine/backtest/`, `engine/strategies/rl_*.py`, MES validation outputs |
| Agent 3 | `engine/markets/orchestrator.py` (or equivalent), `engine/risk/cross_market_risk.py`, new correlation modules |
| Agent 4 | `dashboard/app/` pages (validation, scorecard, command-center, portfolio), `dashboard/components/` |
| Agent 5 | `engine/learning/`, `engine/agents/technical_analyst.py` (context wiring), new `/learning/*` endpoints |

If two agents need the same file, use the task manifest to coordinate — only one agent
edits a file at a time.

---

## Progress Files

| Agent | Progress File |
|---|---|
| Agent 1 | `progress.txt` (root) |
| Agent 2 | `progress.txt` (root, shares with Agent 1) |
| Agent 3 | `progress-agent3.txt` |
| Agent 4 | Create `progress-agent4.txt` if not present |
| Agent 5 | Create `progress-agent5.txt` if not present |

Always read the **Codebase Patterns** section at the top of the progress file before
starting a story — it holds critical learnings from previous iterations.

---

## Quality Gates — Ralph Must Enforce

Before marking any story `passes: true`:

```bash
# Engine tests must pass
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Safety layer is sacred
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard build must be clean (for Agent 4 stories)
cd dashboard && pnpm run build

# Secrets check before any commit
bash scripts/hooks/check-secrets.sh
```

**Never mark passes: true with failing tests.** Fix the tests or explain why they
are legitimately skipped (env-dependent only, e.g. TWILIO_ACCOUNT_SID absent).

---

## Commit Format

```
feat: [US-ID] - Story Title
```

Examples:
```
feat: [US-CORR-001] - Map current multi-market orchestrator structure
feat: [US-LEARN-002] - Wire trade-close event to feedback module
feat: [US-DASH-003] - Add portfolio-level P&L chart
```

---

## Safety Rules for Ralph Agents

All ralph agents inherit all JARVIS safety invariants — the autonomous loop does NOT
get any special permissions:

- **Never modify `safety_layer.py`** without explicit Tier 3 confirmation from Matt
  (even if a story seems to require it — stop and ask instead)
- **Never change `INSTRUMENT_PARAMS`** in `signals.py` without walk-forward validation
- **Never set `LIVE_TRADING_ENABLED = True`** — this flag stays False until Phase 3
- **Never write to IB Gateway port 4001** — permanently blocked
- Agent 2 works on MES re-validation analysis only — it does NOT re-enable MES trading
  (MES stays DO NOT TRADE until gates are met and Matt approves)

---

## Resetting the Manifest Before a Multi-Agent Session

Before deploying multiple agents simultaneously, reset the task manifest:

```bash
python3 -c "
import json
with open('.claude/task-manifest.json') as f: m = json.load(f)
for t in m['tasks']: t['status'] = 'unowned'; t['owner'] = None
with open('.claude/task-manifest.json', 'w') as f: json.dump(m, f, indent=2)
print('Manifest reset — ready for 5 agents')
"
```

---

## What to Do When an Agent Stops

Per project instructions: **if an agent stops, start another to replace it.**

1. Note which PRD file the stopped agent owned
2. Check that agent's progress file — see how far it got
3. Open a new session and say: "Continue ralph for Agent N — last story was [US-ID]"
4. The new agent reads the PRD, sees which stories still have `passes: false`, and continues

The loop never stops. 5 agents always working.

---

## Current Priority Order

Based on remaining work and impact:

1. **Agent 2** — 2 stories left (MES-006, MES-007). Finish this first.
2. **Agent 5** — Learning system wiring. This is a P0 blocker (learning loop disconnected).
3. **Agent 3** — Correlation monitoring. Required for safe multi-instrument trading.
4. **Agent 4** — Dashboard. Visual validation of Agent 3 and 5 work.
5. **Agent 1** — Commit triage. Important for repo hygiene but non-blocking.

---

## Reference: Ralph Skill Location

The ralph skill documentation lives at:
`/sessions/tender-beautiful-lovelace/mnt/.claude/skills/ralph/`

Invoke with: `ralph` via the Skill tool, or say "run ralph for Agent N" in any session.
