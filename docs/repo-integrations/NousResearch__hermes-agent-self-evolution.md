---
repo: NousResearch/hermes-agent-self-evolution
url: https://github.com/NousResearch/hermes-agent-self-evolution
language: Python
license: MIT
analyzed_at: 2026-04-19
recommendation: partial-integrate
surfaces_with_value: [rules, skills, docs]
---

# NousResearch/hermes-agent-self-evolution

## Core value proposition

Self-evolving agent framework. Phase 1 uses DSPy + GEPA to evolve prompts
from execution traces. Later phases (Darwinian Evolver) mutate agent code
itself with safety gates. Nous Research's opinionated take on
reflective/autonomic agent improvement.

## License

**MIT** — free to port with attribution.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | defer | Phase-4 code mutation is **HIGH RISK** in a trading system — never ship without safety-review |
| 2 | Project rules | integrate-now | Hermes' "evolution safety gates" map cleanly to a jarvis-trader rule (100% tests pass, size limits, semantic preservation, human PR review) — **add trading-specific guardrails** |
| 3 | Skills | partial-integrate | Phase-1 reflective prompt evolution could evolve `.claude/agents/` + `.claude/skills/` by reading `agent_feedback.db` traces. Depends on #2 being shipped first |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | no-fit | Framework assumes DSPy/GEPA stack; not a direct subagent pattern |
| 6 | Docs | integrate-now | Short doc at `docs/research/self-evolution-safety-gates.md` synthesizing the safety-gate rule set |
| 7 | Dev tooling | no-fit | DSPy/GEPA dep adds weight; gated on actual adoption |
| 8 | Dashboard | no-fit | — |
| 9 | Ops | no-fit | — |

## Integration plan

1. **Safety-gate rule** (S, 2h). Write `.claude/rules/evolution-safety.md`
   adapting Hermes' gates: trading adds a hard "no risk-threshold mutation"
   and "mandatory backtest before live" clause.
2. **Doc** (S, 1h). `docs/research/self-evolution-safety-gates.md`.
3. **[DEFERRED] Phase-1 reflective loop**. Requires `AgentFeedbackTracker`
   extension for richer trace capture, DSPy install, and opus-level review
   gate. M-L effort; not in current sprint.

## Red flags (CRITICAL)

- **Phase 4 = code-mutation = PRODUCTION RISK**. Trading code auto-evolving
  silently overfits or fails. **Strictly never** wire Darwinian Evolver to
  `engine/` or `engine/backtest/bayesian_optimizer.py` without explicit
  risk-team approval.
- **Data sparsity**: evolved variants overfit if `agent_feedback.db` has
  < 200 trades or regime-biased (e.g., only TRENDING_BULL).
- **No auto-commit gate**: Hermes enforces human PR review; jarvis-trader
  must match — never auto-commit to `.claude/agents/` or `engine/` from an
  evolved branch.

## Effort

Phase-1 rule + doc: **S (3h total)**. Reflective loop: deferred pending
architecture decision.
