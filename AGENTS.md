# JARVIS Trader — Virtual Engineering Team

Powered by gstack v0.15.1.0. Skills live at `.claude/skills/gstack/`.

## Sprint Workflow

```
Think → Plan → Build → Review → Test → Ship → Reflect
```

| Stage | Skill | When to Use |
|-------|-------|-------------|
| Think | `/office-hours` | Before any new trading feature or agent |
| Plan | `/plan-ceo-review` | Does this feature belong in a live trading system? |
| Plan | `/plan-eng-review` | Lock data flow, safety layer interactions, edge cases |
| Plan | `/plan-design-review` | Any new dashboard page or component |
| Plan | `/autoplan` | Run all three plan reviews automatically |
| Build | *(code)* | Implement against the locked plan |
| Review | `/review` | **Required** before any merge touching `engine/risk/safety_layer.py` |
| Review | `/codex` | Cross-model second opinion for complex algorithm changes |
| Review | `/cso` | Periodic OWASP + STRIDE security audit of FastAPI engine |
| Test | `/qa` | Browser QA on dashboard at http://localhost:3010 |
| Test | `/qa-only` | QA report only — no auto-fixes |
| Test | `/benchmark` | Measure LLM pipeline latency before/after changes |
| Ship | `/ship` | Run tests → review → push → PR (replaces manual git workflow) |
| Ship | `/land-and-deploy` | Merge → deploy → canary verify |
| Reflect | `/retro` | Weekly retro with shipping streaks |
| Reflect | `/learn` | Capture per-session learnings |
| Reflect | `/document-release` | Update docs to match what shipped |

## Safety-Critical Rules

These apply on top of normal gstack workflow:

- `/review` is **mandatory** before merging any PR that touches:
  - `engine/risk/safety_layer.py`
  - `engine/config.py` (TradingConfig risk params)
  - `engine/backtest/signals.py`
  - Any IB Gateway or Schwab connector code
- Use `/investigate` instead of `print()` debugging for agent pipeline failures
- Use `/canary` after deploying engine changes that affect live paper trading
- `/careful` is always active for this repo (destructive command warnings)

## Browser Testing

The `/browse` skill controls real Chromium. Use `$B <command>` directly:

```bash
# Snapshot the dashboard
$B goto http://localhost:3010
$B snapshot

# Click through a trade workflow
$B click "New Trade"
$B snapshot

# Fill a form
$B fill "#symbol" "MCL"
$B click "Submit"
```

Dashboard runs on port 3010. Engine API runs on port 8010.

## JARVIS Trader Architecture → gstack Skill Map

| Component | Relevant Skills |
|-----------|----------------|
| 5-stage LLM pipeline | `/review`, `/investigate`, `/benchmark` |
| Next.js dashboard | `/qa`, `/design-review`, `/browse` |
| FastAPI engine | `/review`, `/cso`, `/qa` |
| Learning system | `/review`, `/investigate` |
| Multi-market orchestrator | `/plan-eng-review`, `/review` |
| Release workflow | `/ship`, `/land-and-deploy`, `/document-release` |

## Available Skills (33 total)

```
/autoplan          /benchmark         /browse
/canary            /careful           /checkpoint
/codex             /connect-chrome    /cso
/design-consultation  /design-html    /design-review
/design-shotgun    /document-release  /freeze
/gstack-upgrade    /guard             /health
/investigate       /land-and-deploy   /learn
/office-hours      /plan-ceo-review   /plan-design-review
/plan-eng-review   /qa                /qa-only
/retro             /review            /setup-browser-cookies
/setup-deploy      /ship              /unfreeze
```

## First-Time Setup

```bash
# Build browse/design binaries (requires Bun v1.0+)
cd .claude/skills/gstack && ./setup

# Windows/WSL2:
wsl -- bash -c "cd /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/.claude/skills/gstack && ./setup"
```

See `.claude/skills/gstack/GSTACK-INSTALL.md` for full setup guide.
