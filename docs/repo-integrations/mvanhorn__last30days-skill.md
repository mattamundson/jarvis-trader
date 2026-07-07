---
repo: mvanhorn/last30days-skill
url: https://github.com/mvanhorn/last30days-skill
stars: 22329
language: Python
license: MIT
archived: false
pushed_at: 2026-04-15T19:19:50Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [project_skills, docs, ops_messaging]
---

# mvanhorn/last30days-skill

## Core value proposition

Last30days-skill is a multi-source research aggregator that queries Reddit, X, YouTube, TikTok, Polymarket, GitHub, and web search in parallel, scores results by real engagement metrics (upvotes, odds, view counts), and synthesizes findings into a single brief. It ships as a Claude Code plugin, OpenClaw skill, and standalone Python library with zero-config defaults.

## Surface analysis

### 1. Engine code
**no-fit** — The repo contains no trading signals, backtesting harnesses, risk checks, or portfolio logic. Its research pipeline (multi-source API orchestration, entity resolution, synthesis) lives in Python but operates outside the trading domain. News sentiment is adjacent (engine/agents/news_analyst.py exists) but last30days operates at a broader information layer.

### 2. Project rules
**no-fit** — No coding discipline, safety invariants, or testing patterns that would enhance `.claude/rules/`. The repo's LLM synthesis prompts are domain-neutral (work for any research topic) vs. jarvis-trader's safety-first trading rules.

### 3. Project skills
**partial-integrate** — last30days-skill has a reusable skill design: SKILL.md (runtime spec), multi-platform setup (Claude Code, OpenClaw, Gemini), and a unified CLI entry point (`/last30days <query>`). This format mirrors jarvis-trader's own 5-skill directory structure (agent-debate-explain, backtest-report, gstack, jarvis-trader, pm2-doctor). Candidate integration: Create `.claude/skills/last30days/SKILL.md` as a wrapper that maps `/last30days <symbol|topic>` to the plugin, with jarvis-trader context (market hours gating, portfolio symbol prefilling). **Blocker**: requires user to install plugin first (can link in SKILL.md). Effort if integrated: ~2 hours (wrapper + routing).

### 4. Slash commands
**no-fit** — No `/last30days`-style commands exist in jarvis-trader today (commands live in `.claude/commands/*.md`). A `/research <topic>` command could wrap the skill, but that's a skill integration consequence, not a standalone surface fit.

### 5. Subagents
**no-fit** — last30days does not define a specialized reviewer or analyzer agent. It synthesizes existing research, not a tier in a multi-agent decision chain. The repo's entity-resolution "pre-research brain" is a pre-search classifier, not an agent that feeds debate or portfolio decisions.

### 6. Docs
**defer** — The repo's 8,000+ line README (features, API docs, setup) would be valuable as a research-workflow reference in `docs/runbooks/` or `docs/strategy/`. However, jarvis-trader's knowledge base is trading-focused; a general-purpose research guide would require a new `docs/research-workflows/last30days.md` *only if* the team decides to ship `/last30days` as a standard pre-trade research step. Decision required first.

### 7. Dev tooling
**no-fit** — No CI/CD patterns, PM2 configurations, pre-commit hooks, or GitHub Actions. last30days uses standard Python + Node tooling already covered by jarvis-trader's ecosystem.

### 8. Dashboard
**no-fit** — No UI components, Tailwind patterns, or monitoring widgets. last30days is CLI/plugin-native; any dashboard integration (e.g., "show recent research results") would be a net-new component.

### 9. Ops / messaging
**partial-integrate** — last30days can be invoked as a pre-market research fetch (e.g., via `engine/schedulers/eod_scheduler.py` or a new cron). The morning brief (`engine/notifications/morning_brief.py`, 259 lines) currently assembles portfolio + macro + news; extending it to call `/last30days` for trending topics (e.g., "crude oil", "Fed decision", competitor moves) would add grounded recency. **Blocker**: requires user credential setup (X auth, YouTube/TikTok tokens, Polymarket API) — same auth/key burden as existing news sources. Current morning_brief queries `discord_corey_commentary`, `corey_session_bias`, macro indicators; adding last30days would require a new `research_topics` list in config and a call to the skill/plugin at cron time.

## Integration plan

### Surface 3 (Project skills) — RECOMMENDED FOR USER REVIEW
**File**: `.claude/skills/last30days/SKILL.md`
**Steps**:
1. Verify user has `/plugin marketplace add mvanhorn/last30days-skill` installed (or `clawhub install last30days-official` if using OpenClaw).
2. Create a thin wrapper skill that documents:
   - How to invoke: `/last30days <symbol>` (e.g., `/last30days MCL` or `/last30days "AI regulation"`)
   - When to use: before any trade setup, after major news events, or to validate trade thesis vs. community sentiment
   - jarvis-trader context: market hours gating (only within Globex 5pm–4pm CT) to avoid stale data queries during closed markets
   - Output format: expects markdown brief with "Best Takes" section and entity summaries
3. Link from `.claude/skills/jarvis-trader/SKILL.md` as a supporting skill.
4. Effort: S (1–2 hours).

### Surface 9 (Ops / messaging) — OPTIONAL, FUTURE DECISION
**File**: `engine/schedulers/` + `engine/notifications/`
**Steps** (decision gate required):
1. Define `RESEARCH_TOPICS` in `engine/config.py` (e.g., `["crude oil", "Fed announcements"]`).
2. Add a cron job or extend `morning_brief.py` to call `/last30days` for each topic.
3. Pipe results into the morning brief or a new `daily_research.txt` in the dashboard.
4. Effort: M (4–6 hours) — includes credential setup, testing, and integration test.

### All other surfaces
No integrations. The repo is a research utility, not a trading engine extension.

## License & attribution

MIT license. If integrating, add header to `.claude/skills/last30days/SKILL.md`:
```
Based on [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) (MIT license).
```

## Effort estimate

- **Surface 3 (skill wrapper)**: S (1–2 hours)
- **Surface 9 (cron integration)**: M (4–6 hours, decision gate required)
- **Total if both**: M–L (5–8 hours)

## Red flags

1. **Auth overhead**: TikTok, Instagram, YouTube, X all require API keys or browser sessions. User must populate these in OpenClaw config or local env. The `setup wizard` works on demand but not in automated cron context.
2. **Rate limits**: Reddit (free), X (browser auth), Polymarket (free). YouTube/TikTok require ScrapeCreators token (10K free calls). Cron invocation could exhaust tokens if run frequently.
3. **Recency bias**: Polymarket odds and Reddit posts are real-time signals; morning brief running at 8:45 CT captures 6-hour-old X posts (X API queries last 7 days by default). May need v3 feature tuning (entity disambiguation for markets) to avoid noise.
4. **Not trading-integrated**: last30days synthesizes background research; it does not feed the debate/trader agents. Use case is human pre-trade validation, not autonomous signal generation.

## Notes for user

This repo is **not a blocker** — jarvis-trader runs fine without it. Value is:
- *If research is part of your pre-trade ritual*: Skill wrapper (1 hour) adds `/last30days <symbol>` as a Claude Code feature.
- *If you want to automate research in your morning brief*: Ops integration (4–6 hours) adds a daily research section. Requires auth setup and a go/no-go decision on automation vs. manual research.
- *If neither applies*: Classify as `defer` and revisit if the team decides systematic research is a trading edge.

Recommend: Start with skill wrapper (Surface 3) as a low-risk proof of concept. User can then decide whether to proceed with cron automation (Surface 9).
