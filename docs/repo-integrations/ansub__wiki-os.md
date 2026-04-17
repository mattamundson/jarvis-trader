---
repo: Ansub/wiki-os
url: https://github.com/Ansub/wiki-os
stars: 176
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-12
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [Docs]
---

# Ansub/wiki-os

## Core value proposition
WikiOS is a local-first web UI layer for Obsidian vaults that provides search indexing, graph visualization, article pages, and statistics. It's a standalone Node.js/TypeScript app (Fastify + React) that reads an Obsidian markdown folder, builds a SQLite index, and exposes a clean web interface with file watching for live updates.

## Surface analysis

### 1. Engine code
**no-fit** — WikiOS is a knowledge-base UI framework, not a trading signal, backtest harness, agent, risk check, or indicator. Jarvis-trader's engine focuses on strategy execution and market data, not note-taking infrastructure. No trading logic to integrate.

### 2. Project rules
**no-fit** — WikiOS enforces best practices for local-first web apps, file watching, and React component structure, but these patterns are already covered by jarvis-trader's existing `.claude/rules/` (coding-style.md, dashboard-typescript.md, engine-python.md). No new discipline gaps identified.

### 3. Project skills
**dedup-docs** — Matt already runs a separate Obsidian second-brain vault at `C:/Users/mattm/second-brain/` (390 markdown files, GitHub-synced, fully operational as of 2026-04-16). WikiOS would provide a polished web UI on top of that vault, but such a feature is documented in the existing memory as explicitly out-of-scope: "Matt already has a separate Obsidian second-brain vault for that — no need to double it up inside jarvis-trader" (`docs/memory-patterns.md`). Deploying WikiOS would duplicate knowledge-management responsibility across two vaults.

### 4. Slash commands
**no-fit** — WikiOS is not a CLI tool or command-line extension. It's a web app. No slash commands map to its functionality.

### 5. Subagents
**no-fit** — WikiOS requires no specialized agents. Its file-watching and indexing are runtime background tasks handled by Fastify, not Claude agents. The second-brain vault already has a session-scribe agent (stubbed in `~/.claude/`) for note capture; WikiOS does not enhance that.

### 6. Docs
**dedup-docs** — WikiOS is a knowledge-base visualizer. Jarvis-trader's runbooks, architecture docs, and incident notes all live in `docs/` and `C:/Users/mattm/second-brain/`. Adding a WikiOS instance for jarvis-trader would create a third parallel knowledge source (engine code, Discord/MEMORY.md, second-brain vault, WikiOS instance). The maintenance burden exceeds the value unless jarvis-trader docs are split from strategy docs — a decision not yet made. Current guidance in memory: keep separate from jarvis-trader core.

### 7. Dev tooling
**no-fit** — WikiOS is not a CI tool, pre-commit hook, PM2 pattern, or workflow automation. It's a runtime web server. Jarvis-trader's dev tooling (`.github/workflows/`, `.claude/hooks/`) focuses on testing, linting, and engine health — orthogonal to knowledge indexing.

### 8. Dashboard
**defer** — WikiOS includes a polished React dashboard (homepage, search, graph view, stats) built on Tailwind. The dashboard tech stack (React, TypeScript, Tailwind) matches jarvis-trader's stack exactly (`dashboard/components/`, `dashboard/lib/`). However, integrating WikiOS as a tab in the trading dashboard would require: (a) deciding whether the trading dashboard should host knowledge-base views at all, (b) mapping WikiOS's vault structure to jarvis-trader's trading context (agent reasoning logs, portfolio state, etc., not personal notes), (c) potential conflicts if both dashboards run on port 3010. Blocked pending a cross-functional decision (UI/UX for trading + knowledge).

### 9. Ops / messaging
**no-fit** — WikiOS does not generate alerts, notifications, or scheduled tasks. It's a read-heavy web UI. Jarvis-trader's ops layer (`engine/notifications/`, `engine/schedulers/`, WhatsApp/OpenClaw/Discord) focuses on trading signals, market hours gates, and approval workflows — unrelated to knowledge indexing.

## Integration plan
No integrations recommended at this time. The primary value (a polished web UI for Obsidian vaults) is redundant with Matt's existing second-brain setup, and deploying WikiOS inside jarvis-trader would fragment knowledge ownership without clear trading value.

**If reconsider later:** WikiOS could be deployed as a *side-by-side* web service on port 3100 (separate from dashboard port 3010) specifically for indexing engine logs, trade journals, and agent reasoning transcripts (not personal notes). This would require: (1) a new `wiki-os-config.ts` pointing to `docs/` and `engine/logs/` instead of a vault, (2) custom schema mapping for trading-specific metadata (symbols, PnL, agent names, timestamps), (3) a second PM2 process. Effort: **XL** (1-3 weeks for schema + integration + testing). Recommendation: defer until dashboard search capabilities are exhausted or wiki-specific graph analysis adds measurable trading value.

## License & attribution
WikiOS is MIT licensed. If future integration proceeds, add attribution in file headers of any modified WikiOS code: `Derived from github.com/Ansub/wiki-os (MIT)`.

## Effort estimate
N/A (no integration planned). If surface 8 is revisited: **XL** (1-3 weeks).

## Red flags
- **Architectural mismatch**: WikiOS targets personal knowledge vaults; jarvis-trader is a trading system. Forcing a knowledge-base UI into the trading dashboard dilutes both domains.
- **Already solved locally**: Matt has a mature, GitHub-synced Obsidian vault with session-scribe automation. WikiOS adds operational overhead for minimal new functionality.
- **Port/process contention**: The trading dashboard (port 3010) is already under active development. Adding a second web service (WikiOS on port 3010 or 3100) requires PM2 coordination and potential conflicts.
- **Scope creep**: Integrating WikiOS would pull focus away from core trading features (execution, signal generation, risk) into infrastructure (knowledge indexing). Not justified by current roadmap.
