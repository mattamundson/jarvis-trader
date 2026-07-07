---
repo: Open-Dev-Society/OpenStock
url: https://github.com/Open-Dev-Society/OpenStock
stars: 10552
language: TypeScript
license: AGPL-3.0
archived: false
pushed_at: 2026-03-30T06:11:57Z
analyzed_at: 2026-04-18
recommendation: partial-integrate
surfaces_with_value: [dashboard, dev-tooling, docs]
---

# Open-Dev-Society/OpenStock

## Core value proposition

OpenStock is a free, open-source stock market platform offering real-time price tracking, personalized alerts, and company insights via a Next.js + TypeScript + Tailwind UI. Built on MongoDB, Finnhub, TradingView widgets, Inngest (background jobs), and Better Auth. Primary use case is equity research and portfolio monitoring, not algorithmic trading.

## Surface analysis

### 1. Engine code
**no-fit** — OpenStock is frontend-heavy equity research tool. jarvis-trader is Python-based futures execution engine (FastAPI). No algorithmic trading signals, backtest harness, risk management, or data pipeline patterns transfer. Stock data through Finnhub vs. futures data through ThinkorSwim API. Architecturally incompatible.

### 2. Project rules
**no-fit** — OpenStock lacks formalized engineering discipline (no `.claude/rules/`). readme emphasizes beginner-welcoming culture, not safety invariants or testing patterns jarvis-trader requires for live futures trading.

### 3. Project skills
**defer** — OpenStock's Inngest + cron workflow pattern (daily news summaries, AI-personalized welcome emails) has merit for jarvis-trader's notification/scheduler subsystem, but requires dependency audit. Inngest is Node.js-only; jarvis-trader uses Python Celery + Redis. Would require async wrapper or separate Node.js microservice. Estimated effort M-L.

### 4. Slash commands
**no-fit** — OpenStock's command palette (`/search`, `/watchlist`) targets equity research UX. jarvis-trader's slash commands are risk/trade-focused (e.g., `/pretrade-check`, `/kill-switch`). No conceptual overlap.

### 5. Subagents
**no-fit** — OpenStock has no specialized agents. jarvis-trader's multi-agent debate + approval framework is trading-specific; no equity research patterns to port.

### 6. Docs
**partial-integrate** — OpenStock's README, tech stack overview, and onboarding flow model beginner-friendly documentation. jarvis-trader could benefit from similar clarity in `docs/onboarding/`. However, no trading-specific runbooks, risk frameworks, or API contracts to borrow. Value is tone + structure, not content. Effort: S (rewrite for futures context).

### 7. Dev tooling
**integrate-now** — Strong fit on Docker Compose setup, PM2 configuration pattern (`ecosystem.config.js`), and environment variable organization. OpenStock's Docker MongoDB + app service setup is reusable template. jarvis-trader already has `ecosystem.config.js`; OpenStock's pattern is cleaner. Also: `.env.example` documentation approach is exemplary. Effort: S (adapt Docker Compose to jarvis-trader's Python stack).

### 8. Dashboard
**integrate-now** — OpenStock's shadcn/ui + Tailwind v4 component architecture, responsive heatmap/quote widgets (via TradingView embeds), and dark-theme-by-default design are directly reusable. jarvis-trader's dashboard is minimal; OpenStock's polished UI patterns (form inputs, command palette, real-time quote display) can improve UX. TypeScript/React codebase; would require copy-adapt of component patterns to jarvis-trader's Vue/Svelte if applicable, or as inspiration. Effort: M (integrate 3-5 key components).

### 9. Ops / messaging
**defer** — OpenStock uses Nodemailer + Gmail for email notifications. jarvis-trader likely has different notification stack (Discord, WhatsApp, ThinkorSwim alerts). Email templates from OpenStock (welcome, daily digest) could be adapted for market-related alerts, but require trigger and personalization rules for futures context. Effort: M.

## Integration plan

### Integrate-now items

**7. Dev tooling** — Copy `docker-compose.yml` structure and `.env.example` organization:
- Adapt MongoDB service config to jarvis-trader's Python setup
- Reuse environment variable naming conventions
- Update `ecosystem.config.js` comment style if helpful
- File: `engine/docker-compose.yml` (or append to existing)
- Effort: S (< 2hr)

**8. Dashboard** — Audit and port 2-3 key component patterns:
- Command palette (Cmd/Ctrl+K search) from shadcn/ui + cmdk
- Quote ticker display with responsive grid
- Heatmap widget wrapper (already uses TradingView)
- Location: `dashboard/components/` or equivalent
- Effort: M (2-8hr; includes TypeScript → target stack translation)

### Partial-integrate items

**3. Project skills** — Defer Inngest integration until after docker/dashboard phase. Create ticket: "Evaluate Inngest async pattern for scheduler subsystem replacement (blocking: Python async compatibility audit)". Current jarvis-trader Celery stack may be sufficient; Inngest is "nice-to-have" visual workflow UI, not essential.

**6. Docs** — Create `docs/onboarding/beginner-friendly-overview.md` inspired by OpenStock's manifest + tech stack section. Non-blocking; low priority after engine/dashboard work.

**9. Ops / messaging** — Defer email template reuse until jarvis-trader defines alert taxonomy. Current task: "Define alert types for live trading (margin warnings, fill confirmations, EOD P&L summary)" needed first.

## License & attribution

**AGPL-3.0** — Viral copyleft license. If jarvis-trader integrates code (components, utility functions, Docker config) from OpenStock, the derived work must:
1. Release source code under AGPL-3.0 (or compatible GPL-based license)
2. Credit authors in file headers or `CLAUDE.md`
3. Update LICENSE to reflect dual licensing if not already AGPL

If jarvis-trader is proprietary or uses non-compatible license (MIT, Apache 2.0), cannot integrate *code*, only ideas. Recommend:
- **Reuse approach:** Write new components inspired by OpenStock's patterns, document source in `CLAUDE.md` acknowledgments.
- **Attribution:** Add to `docs/acknowledgments.md`: "OpenStock (AGPL-3.0) provided Docker, UI, and documentation patterns for jarvis-trader v0.2+".

## Effort estimate

**L (1-3 days)** if proceeding with 7+8 (dev tooling + dashboard). Breakdown:
- Docker Compose adapt: S (< 2hr)
- Dashboard components audit + porting: M (4-6hr)
- Testing + integration: S (1-2hr)
- License/attribution cleanup: S (< 1hr)

## Red flags

1. **License conflict** — AGPL-3.0 is more restrictive than typical trading software licensing. If jarvis-trader is closed-source or uses incompatible license, cannot redistribute derived code. Legal review required before merging any files.
2. **Architectural mismatch** — OpenStock is equity-research SPA; jarvis-trader is Python futures engine. No core algorithm, risk model, or execution logic transfers. Integrations are UX/ops only.
3. **Framework incompatibility** — TypeScript/React frontend vs. jarvis-trader's stack (Flask/FastAPI? Vue?). Component patterns translate but require manual porting.
4. **Maintenance burden** — OpenStock is active (10.5k stars, pushed 2026-03-30). jarvis-trader must track AGPL requirements if adopting code; recommend forking rather than submoduling.
5. **Inngest dependency** — OpenStock's workflow engine is attractive but adds Node.js runtime dependency. jarvis-trader should audit Python async alternatives (APScheduler, Temporal) before committing.

---

**Verdict:** OpenStock has immediate value on dashboard UX and DevOps patterns, moderate value on notification/scheduler refactor (deferred), and no value on trading algorithms or risk rules. Recommend proceed with 7+8 (dev tooling + dashboard) as quick wins; defer 3, 6, 9 pending architecture/license decisions.
