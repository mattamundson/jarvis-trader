---
repo: virattt/ai-hedge-fund
url: https://github.com/virattt/ai-hedge-fund
stars: 56347
language: Python
license: null
archived: false
pushed_at: 2026-04-17T21:29:43Z
analyzed_at: 2026-04-19
recommendation: partial-integrate
surfaces_with_value: [engine-code, subagents, docs]
---

# virattt/ai-hedge-fund

## Core value proposition

An educational multi-persona AI hedge fund POC. Analyst agents channeled after
specific investors (Damodaran, Buffett, Munger, Pabrai, Lynch, Burry) produce
valuations; a consensus layer aggregates; a portfolio manager decides
position sizing. 56K+ stars reflects the persona idea's appeal more than the
code's readiness.

## License

**No LICENSE file** → proprietary by default. Patterns only — no code copy.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | partial-integrate | Persona prompts → `engine/agents/rules/agent_prompts.py`; multi-persona consensus routing alongside existing `debate.py` (S, 2h) |
| 2 | Project rules | no-fit | Educational POC; no production discipline |
| 3 | Skills | no-fit | Monolithic FastAPI, not a skill pack |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | integrate-now | 13 persona + 6 specialist agents → 5 high-value personas as optional `.claude/agents/` subagents (M, 8h) |
| 6 | Docs | partial-integrate | Document multi-stage filter + consensus scoring at `docs/strategy/multi-persona-debate-framework.md` (S, 2h) |
| 7 | Dev tooling | no-fit | Plain Poetry/pytest/FastAPI |
| 8 | Dashboard | no-fit | Equity-specific KPIs don't transfer to futures |
| 9 | Ops / messaging | no-fit | — |

## Integration plan

1. **Personas → prompts** (S, 2h). Adapt Damodaran, Buffett, Munger, Pabrai,
   Burry prompts to futures/macro context. Gate behind `USE_PERSONA_DEBATE=false`.
2. **Subagents** (M, 8h). Create `.claude/agents/value-investor-deep-dive.md`
   (Damodaran/Munger) and `.claude/agents/tail-risk-advisor.md` (Burry). Wire
   to `engine/agents/pipeline.py` post-debate.
3. **Doc** (S, 2h, blocks on step 2). `docs/strategy/multi-persona-debate-framework.md`
   — persona-by-regime assignment + consensus scoring formula.

## Red flags

1. **Proprietary** — No LICENSE. Ideas only, no code copy.
2. **Stock-only domain** — Persona valuations (P/E, dividends, sector) don't
   map to futures. Prompt rewrite required before validation.
3. **No real execution** — Educational POC. Must pass `engine/tests/test_backtest.py`
   before any live wiring.
4. **Implicit consensus algo** — Not documented in README. Reverse-engineer
   or contact `@virattt` before step 3.
5. **Prompt drift** — LLM version changes degrade consistency. Lock prompts
   in JSON + version control + tests.

## Effort

- Steps 1+2+3: **M total (~12h)**.
- Best sequenced after paper-trade validation of MCL/MNQ so persona prompts
  can be evaluated against a stabilized baseline.
