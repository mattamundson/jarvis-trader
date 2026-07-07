---
repo: AgriciDaniel/claude-obsidian
url: https://github.com/AgriciDaniel/claude-obsidian
stars: 1486
language: Shell
license: MIT
archived: false
pushed_at: 2026-04-13T22:15:00Z
analyzed_at: 2026-04-17
recommendation: dedup
surfaces_with_value: [skills, docs, ops]
---

# AgriciDaniel/claude-obsidian

## Core value proposition

A comprehensive Claude Code plugin that automates Obsidian vault management via 10 skills (wiki, ingest, query, lint, save, autoresearch, canvas) and multi-agent orchestration. Implements Andrej Karpathy's LLM Wiki pattern with hot cache session memory, autonomous ingest/cross-reference, and visual canvas layer. Designed for persistent, compounding knowledge bases that evolve without manual filing.

## Surface analysis

### 1. Engine code
**no-fit** — The repo contains no trading strategies, signals, indicators, backtesting harnesses, portfolio logic, or risk management code. The Obsidian plugin architecture is unrelated to futures/options trading infrastructure.

### 2. Project rules
**no-fit** — The repo does not propose coding disciplines, safety invariants, or testing patterns specific to jarvis-trader. Its guidance applies to knowledge management, not trading system architecture.

### 3. Project skills
**dedup-.claude/skills/obsidian-mind** — The jarvis-trader project already has `obsidian-mind` skill (installed per memory.md, 2026-04-16). That skill provides 5 vault commands (vault-standup, vault-wrap-up, vault-audit, vault-ingest, vault-save-insight) and 5 vault agents (context-loader, cross-linker, query-synthesizer, session-scribe, vault-librarian). The claude-obsidian repo provides 10 skills (wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch, canvas + 3 more). While claude-obsidian is more featureful and actively maintained (pushed 2026-04-13), obsidian-mind is already wired into jarvis-trader and the user's second-brain vault (C:\Users\mattm\second-brain, ~283 pages, auto-commit/push hook enabled). Migrating to claude-obsidian would require: (a) reinstalling plugin + skills into jarvis-trader, (b) replicating second-brain's session-log hook and auto-push, (c) testing compatibility with existing IA Gateway + execution workflows. Classified as dedup because the core value (multi-agent vault automation + hot cache) is already shipping in obsidian-mind.

### 4. Slash commands
**dedup-.claude/commands/** — jarvis-trader uses `/jarvis-*` commands (pretrade-check, kill-switch-check, morning-brief, etc.), not vault-related slash commands. The claude-obsidian repo provides `/wiki`, `/save [name]`, `/autoresearch [topic]`, `/canvas` family. These do not conflict with jarvis-trader's command structure, but the equivalent functionality is covered by obsidian-mind's 5 vault commands. No new slash commands needed.

### 5. Subagents
**partial-integrate** — The claude-obsidian repo includes 2 specialized agents (`wiki-ingest.md`, `wiki-lint.md`) for parallel vault ingestion and health checks. The obsidian-mind skill has 5 agents (context-loader, cross-linker, query-synthesizer, session-scribe, vault-librarian). The claude-obsidian agents are not explicitly ported to jarvis-trader. However, the architectural insight (parallel ingest + lint loops) is generic and could be adopted if jarvis-trader ever needs to ingest large training datasets (e.g., Discord message archives, research papers for strategy research). Current blocker: obsidian-mind agents are task-specific; claude-obsidian agents are skill-specific. Effort to backport would be ~2-4 hours but is deferred pending explicit need.

### 6. Docs
**no-fit** — The claude-obsidian README is comprehensive (vault setup, commands, MCP config, plugin reference, file structure). It does not address trading-specific documentation (runbooks, strategy architecture, risk checks). jarvis-trader's `docs/` (CURRENT_STATE.md, JARVIS_TRADER_UNIFIED_CANON.md, runbooks/, troubleshooting.md) is distinct. No operational or architectural value to port.

### 7. Dev tooling
**no-fit** — The repo includes `bin/setup-vault.sh` (vault initialization) and `.obsidian/` config (graph filters, snippets, CSS). jarvis-trader's dev tooling (PM2, Bash restart scripts, pytest, GitHub Actions) is orthogonal. The Obsidian setup script is not transferable to a trading engine project.

### 8. Dashboard
**no-fit** — The claude-obsidian repo includes visual canvas features (Obsidian-native `.canvas` files, layout algorithms, image/PDF rendering). These are knowledge-management UI, not trading dashboard components. jarvis-trader's dashboard (port 3010, Tailwind, React) is a live trading monitor, not a knowledge base. No component reuse.

### 9. Ops / messaging
**no-fit** — The repo specifies session hooks (`hooks.json: SessionStart + Stop hot cache hooks`) and Obsidian Git integration (auto-commits every 15 minutes). jarvis-trader's ops (engine/notifications/openclaw_notifier.py, schedulers/, PM2 cron jobs) is trading-alert-focused. The Obsidian Git hook is specific to vault snapshots, not applicable to engine operations.

## Integration plan

No integrations. The repository's value on surfaces 3, 5 (subagents) is already covered by obsidian-mind, which is actively integrated into jarvis-trader and the user's second-brain vault (verified 2026-04-16). The claude-obsidian repo is more comprehensive and actively maintained (1486 stars, recent push), but migration would disrupt an already-working setup without clear trading-domain benefit. Recommend classifying as **dedup / full architectural coverage via obsidian-mind**.

**Conditional future action**: If jarvis-trader needs to ingest large document archives (e.g., Corey trade session transcripts, research papers) for strategy learning, revisit claude-obsidian's `wiki-ingest` parallel agent pattern and consider adapting it to the training pipeline. That is a separate research task, not an immediate integration.

## License & attribution

MIT license. No code copied; this analysis is a capability comparison.

## Effort estimate

S (classification only; no integration work)

## Red flags

None. The repo is actively maintained (pushed 2026-04-13), MIT-licensed, not archived, well-documented, and has strong community adoption (1486 stars, 165 forks). The only consideration is that jarvis-trader already has equivalent functionality via obsidian-mind, making a migration a feature parity upgrade rather than a bug fix or capability gap. User's existing second-brain vault (283 pages, auto-sync hook) would require careful rebasing if switching plugins, which adds operational friction for marginal gain.

