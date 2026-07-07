---
repo: affaan-m/everything-claude-code
url: https://github.com/affaan-m/everything-claude-code
stars: 158679
language: JavaScript
license: MIT
archived: false
pushed_at: 2026-04-16T03:07:05Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [project rules, project skills, dev tooling]
shipped:
  - skill: .claude/skills/jarvis-search-discipline/SKILL.md (adapted from search-first)
  - skill: .claude/skills/jarvis-cost-routing/SKILL.md (adapted from cost-aware-llm-pipeline)
deferred:
  - hook profile gating (ECC v1.8.0 pattern) — follow-up
  - continuous learning skill extraction — blocked on patterns.py refactor
  - verification eval grader architecture — blocked on oracle choice
---

# affaan-m/everything-claude-code

## Core value proposition

Everything Claude Code (ECC) is a production-ready agent harness performance system developed over 10+ months of intensive daily use building real products. It provides a complete toolkit: 156 skills, 38 agents, 72 legacy command shims, memory persistence hooks, continuous learning infrastructure, security scanning (AgentShield with 1282 tests), multi-language rules, PM2 orchestration, token optimization patterns, and cross-harness support (Claude Code, Codex, Cursor, Gemini). The v1.10.0 surface refresh includes a Tkinter dashboard, Rust ECC 2.0 alpha control plane, and operator workflows.

## Surface analysis

### 1. Engine code
**no-fit** — ECC contains no trading strategies, signals, backtesting harnesses, portfolio logic, or market-specific features. It is a harness performance system, not a trading domain toolkit. JARVIS TRADER's engine is domain-specific (futures, regime filters, hidden pivots) and does not benefit from ECC's agent orchestration code.

### 2. Project rules
**partial-integrate** — ECC's six-part rule architecture (token optimization strategy, memory persistence discipline, hook reliability patterns, continuous learning conventions, verification eval discipline, and parallelization trade-offs) overlaps with existing `.claude/rules/meta-discipline.md` and `.claude/rules/testing.md` but provides deeper, production-tested guidance. 

Current JARVIS state:
- `meta-discipline.md` covers thinking discipline (state assumptions, simplicity, surgical changes, verifiable goals) ✓
- `token-efficiency.md` (user's personal rules) covers model tiering (haiku/sonnet) + parallel agents (10 max) ✓
- `token_optimizer.py` in engine implements prompt caching + model selection ✓
- Hook infrastructure exists (6 hooks wired in `settings.local.json`: PreToolUse, SessionStart, UserPromptSubmit, PostToolUse, Stop) ✓

ECC teaches NOT covered by JARVIS rules:
- Continuous learning + pattern extraction (Skills auto-evolution, instinct-based learning with confidence scoring) — ECC v1.9.0 introduced SQLite state store + session adapters for skill evolution. JARVIS has `AgentFeedbackTracker` (pnl-based scoring) but no auto-skill-generation pipeline.
- Hook-specific reliability patterns (ECC v1.8.0: SessionStart root fallback, Stop-phase summaries, `ECC_HOOK_PROFILE=minimal|standard|strict`, runtime gating) — JARVIS hooks are basic command wrappers with no profile gating or reliability fallbacks.
- Verification eval discipline (checkpoint vs continuous evals, grader types, pass@k metrics) — JARVIS has regression test suite (1484 passing) but no formal grader architecture for agent evals.

**Recommendation**: Defer new rules porting. JARVIS rules are sufficient for current session discipline. Continuous learning (skill evolution) is a roadmap P1 (#Track J) but requires refactoring `engine/agents/patterns.py` (currently inline patterns, not separate extractors). This should land as a dedicated task after current sprint, not as incremental rule additions.

### 3. Project skills
**integrate-now** — ECC's 156 public skills span agent orchestration, security, analytics, and operational workflows. Several are directly reusable or teachable in JARVIS context:

High-value ECC skills for trading context:
- `search-first` (prioritize search over hallucination) — teachable as a sub-skill for research agents
- `cost-aware-llm-pipeline` (model routing, response compression, token budgeting) — directly applicable to JARVIS advisor strategy (which already uses Sonnet/Haiku tiering)
- `skill-stocktake` (inventory existing skills, coverage gaps) — applicable to JARVIS agent taxonomy (38 agents, track learning extraction)
- `/security-scan` (AgentShield integration) — JARVIS has kill-switch, no automated security scanning
- `mcp-server-patterns` (MCP configuration + instantiation) — JARVIS uses Alpaca MCP but no templating library
- `continuous-learning` / instinct-import patterns (v1.9.0) — JARVIS AgentFeedbackTracker + pattern.py, but no auto-extraction

**Concrete plan**: Clone `skills/search-first/SKILL.md`, `skills/cost-aware-llm-pipeline/SKILL.md`, and `skills/continuous-learning/` into `.claude/skills/`. Adapt to JARVIS naming (e.g., `jarvis-cost-routing`, `jarvis-search-discipline`). Test against existing agents (bull_researcher, bear_researcher) first.

**Effort**: M (2-4 hours) — copy, rename, test with debate agent flow.

### 4. Slash commands
**no-fit** — ECC's 72 legacy command shims + new commands (e.g., `/pm2`, `/harness-audit`, `/loop-start`, `/quality-gate`) are Claude Code CLI patterns, not trading-adjacent. JARVIS has domain-specific commands (`/jarvis-morning-brief`, `/jarvis-wfe-check`, `/jarvis-kill-switch-check`) which are more valuable for trading context. ECC commands do not teach patterns JARVIS hasn't already adopted (command structure, matcher routing via `settings.json`).

**Defer**: ECC's `/harness-audit` could teach coverage inspection patterns. Add to roadmap as "audit command coverage" task if needed; not urgent.

### 5. Subagents
**no-fit** — ECC documents 38 specialized subagents (language-specific reviewers, security scanners, cost auditors) for general developer workflows. JARVIS has 5 production subagents (`bull_researcher`, `bear_researcher`, `risk_manager`, `trader`, `advisor_client`) optimized for trading decision-making. ECC agents do not transfer — they reason about code quality, not market microstructure. JARVIS would need to re-author any borrowed agent for trading context (symbol validation, regime awareness, stop-loss invariants).

### 6. Docs
**dedup** — ECC's guidance documents (token optimization, memory persistence, verification loops, parallelization) are well-written but overlap with existing JARVIS docs:
- JARVIS `troubleshooting.md` (100+ lines) covers OpenClaw, WhatsApp, engine restart — operationally complete
- JARVIS `docs/session-logs/handoff-*.md` (7 templates) capture memory persistence + session context
- JARVIS `token-efficiency.md` (user rules) + `engine/utils/token_optimizer.py` cover token discipline

ECC's "Longform Guide" teaches advanced checkpoint vs continuous eval patterns. Teach-ability: MEDIUM. JARVIS would benefit from a formalized `verification-eval-architecture.md` doc, but this is a separate task.

**Defer**: Schedule as a documentation P1 after continuous learning lands (roadmap #Track J).

### 7. Dev tooling
**partial-integrate** — ECC provides production-tested patterns for:

Applicable to JARVIS:
- **Hook reliability system** (ECC v1.8.0: `ECC_HOOK_PROFILE=minimal|standard|strict`, disabled-hooks gating) — JARVIS hooks are simple but lack runtime profile gating. Current `settings.local.json` hardcodes hooks; no gating. Recommended: add `.claude/hooks/profile-*.json` to selectively enable/disable hook chains (e.g., minimal for CI, strict for safety-critical files).
- **PM2 orchestration patterns** (6 commands: `/pm2`, `/multi-plan`, `/multi-execute`, `/multi-backend`, `/multi-frontend`, `/multi-workflow`) — JARVIS uses PM2 (`ecosystem.config.js`) but has no CLI commands. Teachable as `/jarvis-pm2` wrapper around `pm2 list`, `pm2 logs`, `pm2 restart jarvis-engine`.
- **Manifest-driven install** (v1.9.0: `install-plan.js`, `install-apply.js`, state store for incremental updates) — JARVIS does not have plugin management. Not applicable.

Not applicable:
- **Multi-language rule architecture** (TypeScript, Python, Go, Java, Kotlin, PHP, Perl, Rust, C++) — JARVIS is Python + TypeScript; no multi-language build system.
- **Biome hook optimization, PowerShell installer, Antigravity IDE support** — JARVIS uses ESLint (dashboard), pytest (engine), no Windows-specific build constraints.

**Concrete plan**: 
1. Write `.claude/hooks/profile-config.json` with `minimal|standard|strict` modes (gating PreToolUse guards based on mode).
2. Create `/pm2-health` command that wraps `pm2 list | grep jarvis-engine | jq .`.
3. Test mode gating: run hook safety checks in strict mode, skip formatting in minimal mode.

**Effort**: S-M (1-3 hours) — profile config, one new command, hook conditional logic.

### 8. Dashboard
**no-fit** — ECC's new Tkinter GUI (dark/light theme, font customization, logo in taskbar) is a generic agent harness dashboard. JARVIS has a production React dashboard (port 3010, Tailwind, real-time trade monitoring, regime display, learning feedback UI). ECC's dashboard does not inform JARVIS UI patterns; domain mismatch.

### 9. Ops / messaging
**defer** — ECC integrates WhatsApp, Discord, Telegram, and custom MCP servers into a unified notification system. JARVIS already has:
- WhatsApp gateway (`engine/notifications/openclaw_notifier.py`, Twilio backend)
- kill-switch deactivation warnings
- Morning brief (7 AM CT cron), pre-market news (8:30 AM CT), EOD (4 PM CT)
- OpenClaw alerting (BUY/SELL signals to WhatsApp)

ECC's value: pattern library for multi-channel aggregation, rate-limiting, fallback orchestration. JARVIS would benefit from a "notification strategy" doc (e.g., when to use WhatsApp vs. silent-log, retry bounds). Current state is functional but lacks formal strategy.

**Defer**: Add to roadmap as "ops-notification-playbook" task after continuous learning lands.

## Integration plan

### Immediate (can be greenlit this session)
1. **Port search-first + cost-aware-llm-pipeline skills** to `.claude/skills/jarvis-search-discipline/SKILL.md` and `.claude/skills/jarvis-cost-routing/SKILL.md`.
   - Files to copy: `ECC/skills/search-first/SKILL.md`, `ECC/skills/cost-aware-llm-pipeline/SKILL.md`
   - Adaptation: rename examples from "finding APIs" to "market data sourcing", swap cost model (Anthropic → Anthropic trading-optimized)
   - Test: run `/jarvis-search-discipline` in research agent context, verify cost metrics in advisor strategy
   - Effort: M (2-4 hours)

2. **Add hook profile gating** (ECC v1.8.0 pattern).
   - Create `.claude/hooks/profile-config.json` with three modes (minimal/standard/strict).
   - Modify `settings.local.json` hooks to check profile before executing guards.
   - Test: set `CLAUDE_HOOK_PROFILE=minimal`, verify PreToolUse guards are skipped; set `strict`, verify all run.
   - Effort: S (1-2 hours)

### Deferred (roadmap follow-up)
- **Continuous learning skill extraction** (ECC v1.9.0 instinct-based patterns) — blocker: `engine/agents/patterns.py` refactor to separate extractors (roadmap #Track J)
- **Verification eval grader architecture** (ECC checkpoint vs continuous patterns) — blocker: decision on oracle function for trade quality (Sharpe? IC? PnL?)
- **Ops notification playbook** (ECC multi-channel strategy) — after sprint 22 (currently at morning brief + kill-switch + EOD crons)

## License & attribution

MIT license. All ECC files are freely reusable with attribution. Include in file headers:
```
_Adapted from affaan-m/everything-claude-code skill library (MIT)._
```

Or in CLAUDE.md if creating a new rules doc:
```
_Pattern sourced from ECC Agent Harness Performance System (affaan-m/everything-claude-code, MIT)._
```

## Effort estimate

**Immediate integrations**: S-M
- Skill ports: M (2-4 hours, includes testing with research agents)
- Hook profile gating: S (1-2 hours)
- Total: 3-6 hours for both

**All deferred work**: L-XL (spans 2-3 sprints, depends on continuous learning priority)

## Red flags

None. ECC is active (pushed 2026-04-16), MIT-licensed, 158K+ stars, mature ecosystem with 30+ community contributors. No security, licensing, or architectural concerns.

**One observation**: ECC v1.10.0 includes a Rust control-plane prototype (`ecc2/` in-tree) that exposes dashboard/daemon commands. This is alpha-stage and not production-ready. JARVIS should NOT port this; stick to the mature TypeScript/Python skills (v1.9.0 and earlier).

---

## Verification checklist (completed 2026-04-17)

- [x] README fully read (cached markdown + meta.json)
- [x] Nine surfaces cross-referenced against JARVIS codebase
- [x] Existing hooks/skills/rules inventoried (`settings.local.json`, `.claude/rules/`, `.claude/skills/`, `engine/utils/token_optimizer.py`)
- [x] License verified (MIT, no legal blockers)
- [x] Dedup analysis complete (meta-discipline.md, token_optimizer.py, hook infrastructure already in place)
- [x] High-value surfaces identified (rules, skills, dev tooling)
- [x] Concrete integration plans written with effort estimates
- [x] Red flags checked (none found)
