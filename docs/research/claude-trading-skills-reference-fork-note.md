# JARVIS Research Note — claude-trading-skills (mattamundson/claude-trading-skills)

**Source:** `mattamundson/claude-trading-skills`, default branch `main`, 1695 files, fork (archived: no, private: no), pushed 2026-09-01.
**What it is:** A Claude Code skills repo for equity investors/traders — market analysis, charting, economic calendars, screeners, strategy dev.

## Reusable patterns for JARVIS

### 1. Skill/agent structure is the most transferable artifact
- The repo is organized as Claude skills (SKILL.md + scripts + prompts) for discrete trading workflows: market analysis, technical charting, economic calendar, screener, strategy development.
- JARVIS already has agent commands and strategy pages; the transferable piece is the **skill contract pattern**: a skill has a clear input contract, a bounded output (verdict/chart/screen), and an explicit "what this does NOT do" boundary. That boundary discipline is directly applicable to JARVIS strategy pages and agent commands.
- Do NOT import the skills verbatim — they target a different provider/context. Instead, extract the **pattern** into `docs/research/agent-command-contract-pattern.md`.

### 2. Issue templates as workflow capture
- The repo ships structured issue templates (bug report, real-use pitfall, skill improvement, workflow recipe). JARVIS can adopt the "real-use pitfall" template pattern for strategy/research docs — a lightweight way to capture "I tried X, here's what broke" without turning it into a formal ticket.

### 3. PROJECT_VISION document
- Has a `PROJECT_VISION.md` (and Japanese variant). JARVIS strategy research docs can adopt a short vision/objective statement at the top of each strategy doc, so the strategy's intent survives context shifts.

### What NOT to import
- The actual skill scripts/content target Claude Code specifically and a different market context. Do not vendor them into JARVIS.
- No execution wiring; no risk limits.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/agent-command-contract-pattern.md` — distilled contract pattern (input contract, bounded output, explicit exclusion) + the "real-use pitfall" template as a research-capture tool.
- This converts the reference fork's value (structured agent skill discipline) into a JARVIS-native doc pattern.

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
