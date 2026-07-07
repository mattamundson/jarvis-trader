# CLAUDE.md Memory Organization Patterns

_Generated 2026-04-16 from discord-export/digest-raw survey of ~14 repos tagged `claude_md`._
_Propose-only. The root `CLAUDE.md` is not modified by this doc; a human must decide whether to adopt._

## Current jarvis-trader state

- Root `CLAUDE.md` is 47 lines and contains **Paperclip's** project memory (wrong project — leftover from the Paperclip integration).
- No `@path` imports in root CLAUDE.md.
- User-global rules live at `C:\Users\mattm\.claude\rules\` (`token-efficiency.md`, `workflow.md`).
- Auto-memory lives at `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md` (~300 lines, rich).

The root CLAUDE.md does not reflect jarvis-trader at all. This is the highest-leverage fix.

## Patterns observed in survey repos

### 1. Priority-ordered "read first" list (paperclipai/paperclip, fainir/most-capable-agent-system-prompt)

Top of CLAUDE.md enumerates 3-7 docs in exact read order:

```markdown
Before any non-trivial work, read in this order:
1. `AGENTS.md` — contributor rules and V1 contract
2. `doc/GOAL.md` — product vision
3. `doc/SPEC-implementation.md` — concrete V1 build contract
...
```

**Why it helps**: A fresh Claude session lands on CLAUDE.md, follows the list, and is oriented in ~30 seconds instead of grepping the tree. For jarvis-trader this would be e.g. `docs/CURRENT_STATE.md` → `docs/JARVIS_TRADER_UNIFIED_CANON.md` → `docs/runbooks/` → `engine/config.py`.

### 2. `@path` imports (shanraisshan/claude-code-best-practice — documents the official `@path` syntax)

Claude Code expands `@relative/path.md` inline when reading CLAUDE.md, so you can pull in modular docs without manual paste:

```markdown
@.claude/rules/safety.md
@docs/CURRENT_STATE.md
@docs/runbooks/engine-restart.md
```

**Why it helps**: Lets a 47-line root CLAUDE.md pull in hundreds of lines of living docs without duplication. Paperclip already uses this (`@.claude/paperclip/docs/root-memory.md`) — same pattern, different content.

### 3. Per-module CLAUDE.md (agricidaniel/claude-obsidian, coleam00/archon)

Each top-level package gets its own CLAUDE.md:

- `engine/CLAUDE.md` — Python conventions, pytest layout, async rules
- `dashboard/CLAUDE.md` — Next.js 15 conventions, `fetchEngine` vs bare fetch, badge variant enum
- `tools/CLAUDE.md` — one-off scripts, backfill jobs

Claude auto-discovers these when working inside that subdirectory. The root CLAUDE.md then only needs to point at them rather than duplicate rules.

**Why it helps**: The "no bare await fetch" rule currently lives only in `.github/workflows/ci.yml:236-258`. A `dashboard/CLAUDE.md` would state it as a rule, so Claude would not write violations in the first place.

### 4. Rules folder (shanraisshan/claude-code-best-practice, fainir/most-capable-agent-system-prompt)

Matt already does this at the user level (`~/.claude/rules/`). The project-level equivalent is `.claude/rules/*.md` inside the repo, one file per concern (safety, testing, commits, style). Referenced from CLAUDE.md via `@.claude/rules/<name>.md`.

**Why it helps**: Team-shareable (via git) while still modular. The full rules list in `~/.claude/rules/workflow.md` — which is user-private and doesn't travel with the repo — could be forked: universal rules stay in `~/.claude/rules/`, jarvis-trader-specific rules move to `.claude/rules/` and ride along with a clone.

### 5. Non-negotiables block up front (paperclipai/paperclip)

Separate "Non-negotiable rules" section listed as bullets, placed before any "how to set up" content. For jarvis-trader this would include:

- `.env` files never committed (already enforced in `ci.yml`)
- `pnpm` only — npm is broken system-wide
- `engine/.venv/Scripts/python` only — never system Python
- Dashboard badge variants: strictly `"bull" | "bear" | "warn" | "info" | "neutral"`
- Engine restart via `.\restart_engine.ps1` only — no `--reload` flag
- Live IB Gateway port 4001 is permanently blocked; paper only on 4002
- Never work on Greenfield Metal Sales inside a trading session

### 6. Dev quick-start block (paperclipai/paperclip, most surveyed repos)

Single fenced shell block with the 3-5 commands a new contributor needs. Lets Claude spin a fresh dev loop from cold without re-reading docs.

## Proposed root CLAUDE.md structure for jarvis-trader

_For human review — do not auto-apply._

```markdown
# jarvis-trader — project memory

AI-powered futures & options trading engine for Matt Morrison.
Capital $10K total, $5K/instrument (MCL + MNQ). Paper mode on IB Gateway port 4002.

## Read first (in order)

1. `docs/CURRENT_STATE.md` — latest P0/P1/P2 status
2. `docs/JARVIS_TRADER_UNIFIED_CANON.md` — canonical architecture
3. `docs/runbooks/` — operational playbooks
4. `engine/config.py` — hardcoded safety limits (DO NOT modify without [safety-review])
5. `AGENTS.md` if present, else skip

## Non-negotiable rules

- `.env` files NEVER committed. Real keys live in `engine/.env` (gitignored).
- `pnpm` for all Node. System `npm` is broken.
- Python: `engine/.venv/Scripts/python` only. Never system Python 3.14 or Store Python.
- TS check: `./node_modules/.bin/tsc --noEmit` (not `npx tsc`).
- Dashboard badge variants: `"bull" | "bear" | "warn" | "info" | "neutral"` (strict).
- No bare `await fetch(...)` in `dashboard/` — use `fetchEngine`/`postEngine` from `dashboard/lib/api.ts`.
- Engine restart: `.\restart_engine.ps1`. Never use `--reload` (causes duplicate IB connections).
- Live IB Gateway port 4001 is permanently blocked — paper only (port 4002, account DUP662235).
- Any change to `engine/config.py`, `engine/risk/`, or kill-switch code requires `[safety-review]` PR tag.

## Dev quick-start

\`\`\`bash
# Engine
cd engine && .venv/Scripts/activate && python main.py   # http://localhost:8010

# Dashboard
cd dashboard && pnpm install && pnpm dev                # http://localhost:3010

# Tests
cd engine && pytest -m "not slow"                       # fast suite
\`\`\`

## Imports

@.claude/rules/safety.md
@.claude/rules/testing.md
@docs/CURRENT_STATE.md
\`\`\`

Proposed new files to accompany the rewrite:

- `.claude/rules/safety.md` — kill switch, position sizing, stop-loss direction invariants
- `.claude/rules/testing.md` — pytest markers, fast vs slow, mypy allowlist
- `.claude/rules/commits.md` — conventional commits, never `git add -A`
- `engine/CLAUDE.md` — Python/async conventions
- `dashboard/CLAUDE.md` — Next.js 15, badge variants, fetch wrapper rules

## What NOT to adopt

- **Self-modifying CLAUDE.md** (fainir/most-capable-agent-system-prompt). The "agent rewrites its own memory" pattern is neat but risky for a trading system where invariants must not drift silently.
- **Graph-view / wiki-style memory** (agricidaniel/claude-obsidian). Matt already has a separate Obsidian second-brain vault for that — no need to double it up inside jarvis-trader.

## Source digests referenced

- `C:\Users\mattm\discord-export\digest-raw\github\paperclipai__paperclip.md` (priority list, non-negotiables, @path)
- `C:\Users\mattm\discord-export\digest-raw\github\shanraisshan__claude-code-best-practice.md` (rules folder, @path syntax)
- `C:\Users\mattm\discord-export\digest-raw\github\agricidaniel__claude-obsidian.md` (per-module memory)
- `C:\Users\mattm\discord-export\digest-raw\github\fainir__most-capable-agent-system-prompt.md` (read-order contract)
- `C:\Users\mattm\discord-export\digest-raw\github\coleam00__archon.md` (module CLAUDE.md)
