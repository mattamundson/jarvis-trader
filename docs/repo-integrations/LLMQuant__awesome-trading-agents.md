---
repo: LLMQuant/awesome-trading-agents
url: https://github.com/LLMQuant/awesome-trading-agents
stars: 229
language: Markdown (awesome list)
license: CC0-1.0 (list content; linked sub-repos carry their own licenses)
archived: false
pushed_at: 2026-06 (actively maintained)
analyzed_at: 2026-06-17
recommendation: partial-integrate
surfaces_with_value: [docs, skills, engine, rules]
---

# LLMQuant/awesome-trading-agents

## Core value proposition
A curated directory (~70 entries) of LLM-driven trading agents, MCP servers, agent
Skill packs, benchmarks, and papers. It is a **meta-resource**, not shippable code —
its value to jarvis-trader is (a) a prioritized research backlog of sub-repos to mine,
(b) confirmation that our core architecture matches the field's reference design
(TauricResearch/TradingAgents), and (c) a few specific patterns and Skill packs worth
forking. The list itself is CC0; each linked repo must be license-checked individually
before any code is copied.

## Architecture confirmation (why this matters)
Our pipeline (`engine/agents/pipeline.py`: parallel analysts → bull/bear debate →
trader → risk manager → fund manager) is a direct implementation of the
**TradingAgents** paper (arXiv 2412.20138), the single most-referenced entry in the
list. We are not behind the curve — we are on the canonical design. The list's value
is therefore *incremental*: specific mechanisms layered on top, not a rewrite.

## Surface analysis

### 1. Engine code
**partial-integrate** — The list contains no code, but three linked patterns map onto
existing modules and are worth mining as follow-ups:
- **FinStep-AI/ContestTrade** (agents compete internally before final selection) →
  layers onto `engine/agents/debate.py` + `engine/backtest/consensus.py` /
  `candidate_registry.py`. Tournament-style candidate selection across multiple
  strategy proposals, not just bull-vs-bear.
- **mnemox-ai/tradememory-protocol** (episodic trade-memory MCP, 17 tools) → compare
  against our existing `engine/learning/pattern_db.py` + `consolidator.py`. Likely a
  schema/retrieval-API refinement, not a replacement.
- **ulab-uiuc/live-trade-bench** + **HKUSTDial/DeepFund** (live, point-in-time agent
  benchmarks) → methodology for `engine/backtest/evaluation_harness.py` and
  `paper_tracker.py`. See rules note below re: look-ahead bias.
- **paperswithbacktest/pwb-alphaevolve** (AlphaEvolve strategy evolution) →
  **dedup** with `engine/strategies/discovery_loop.py` + `llm_sandbox.py`, which
  already implement generate→sandbox→backtest→verdict→evolve.

### 2. Project rules
**partial-integrate** — The DeepFund paper ("Time Travel is Cheating: Going Live…",
arXiv 2505.11065) is a clean, citable articulation of point-in-time / look-ahead-bias
discipline. Candidate one-paragraph addition to `.claude/rules/testing.md` or a new
`backtest-integrity` note: every backtest and WFE run must use only data available at
decision time. We already enforce pieces of this (`news_blackout.py`, regime gating),
but there is no single rule stating the invariant.

### 3. Project skills
**partial-integrate** — Several CC-style Skill packs are worth evaluating against our
`.claude/skills/`:
- **marketcalls/vectorbt-backtesting-skills** → we already use vectorbt
  (`engine/requirements.txt`) and have `backtest-report`; this could enrich the
  backtest skill with optimization/comparison templates.
- **tradermonty/claude-trading-skills**, **himself65/finance-skills**,
  **staskh/trading_skills** (option-trader pack with IBKR/MCP) → harvest individual
  skill ideas (breadth, regime, options-flow workflows), do **not** bulk-import.
- **MobiusQuant/OpenMobius-skill** (ICT/SMC) → only if we add SMC signals; otherwise
  no-fit.

### 4. Slash commands
**no-fit** — The list contains no command definitions.

### 5. Subagents
**no-fit** — No subagent definitions; our `.claude/agents/` roster
(pipeline-debugger, backtest-runner, safety-reviewer) already covers our pipeline.

### 6. Docs
**integrate-now** — This is the primary fit. Seed `docs/research-backlog-from-discord.md`
(or a new `docs/repo-integrations/_backlog-trading-agents.md`) with a deduplicated,
prioritized shortlist of the ~6 sub-repos above so they get individually run through
this same repo-integrator skill. The list also belongs in `docs/digest/` as a
corroborating source for our multi-agent architecture.

### 7. Dev tooling
**no-fit** — No CI, hooks, or PM2 patterns.

### 8. Dashboard
**no-fit** — No UI components.

### 9. Ops / messaging
**defer** — Two data MCPs could feed existing agents: **6551Team/opennews-mcp**
(84+ news sources, impact-scoring, WebSocket) → `engine/agents/news_analyst.py` /
`engine/data/`; and the IBKR MCPs (**rcontesti/IB_MCP**, **code-rabi/interactive-brokers-mcp**)
as an alternative interface to our direct IB Gateway connection. Both are deferred —
we already have working news ingestion and a hardcoded IB Gateway path (port 4002,
safety-critical), so neither is a quick win and the IB one touches Tier 3 surface.

## Integration plan
1. **(integrate-now, docs)** Create a prioritized backlog entry listing the 6 mineable
   sub-repos (ContestTrade, tradememory-protocol, live-trade-bench, DeepFund,
   vectorbt-backtesting-skills, opennews-mcp) for individual repo-integrator runs.
2. **(partial, rules)** Draft a look-ahead-bias invariant paragraph citing DeepFund,
   for `.claude/rules/testing.md` — separate PR, no safety tag needed.
3. **(partial, engine)** Schedule individual deep-dives on ContestTrade (tournament
   selection) and tradememory-protocol (memory schema) — each its own analysis doc.
4. Everything else: no action; recorded here so the repo is marked analyzed.

## License & attribution
List content is **CC0-1.0** (public domain) — free to reference and quote, attribute
in this doc. Any code copied from a *linked* sub-repo requires that repo's own license
check (this skill's step 4) before integration — most are MIT/Apache but several
A-share repos are unlicensed (treat as proprietary).

## Effort estimate
**S** for the doc-seeding + rules paragraph (<2hr). Each downstream sub-repo deep-dive
is its own S–M task.

## Red flags
- The list itself ships **no code** — resist treating any entry as plug-and-play.
- Linked repos vary wildly in quality, license, and maintenance; several are
  single-author A-share demos with no LICENSE (proprietary by default).
- IBKR MCP entries touch our Tier 3 broker surface — any move there needs explicit
  confirmation and `[safety-review]`, never a silent swap of the IB Gateway path.
