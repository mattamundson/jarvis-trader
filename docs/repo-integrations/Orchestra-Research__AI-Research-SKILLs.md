---
repo: Orchestra-Research/AI-Research-SKILLs
url: https://github.com/Orchestra-Research/AI-Research-SKILLs
stars: 7083
language: Python
license: MIT
archived: false
pushed_at: 2026-04-13
analyzed_at: 2026-04-19
recommendation: defer
surfaces_with_value: []
---

# Orchestra-Research/AI-Research-SKILLs

## Core value proposition

A 87-skill Claude Code skill pack for AI research workflows — autoresearch
orchestration, paper writing, fine-tuning, distributed training (Megatron,
vLLM, TRL), MLOps, mechanistic interpretability. **Domain: ML research, not
trading.**

## License

**MIT** — would be free to port; nothing to port yet.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | no-fit | ML research infrastructure, not trading |
| 2 | Project rules | no-fit | — |
| 3 | Skills | no-fit | 87 skills, **0 overlap** with trading workflows. Research-only (autoresearch, paper-writing, distributed-training) |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | no-fit | — |
| 6 | Docs | no-fit | — |
| 7 | Dev tooling | no-fit | DSPy, Megatron, vLLM — heavy stack, not relevant |
| 8 | Dashboard | no-fit | — |
| 9 | Ops | no-fit | — |

## Existing jarvis-trader skill landscape (for dedup check)

Research-adjacent skills already present:
- `last30days` — pre-trade sentiment/news research (different scope)
- `jarvis-trader` — core trading agent
- `pm2-doctor`, `backtest-report`, `agent-debate-explain` — trading-specific

**Result: 0/87 skills overlap.** No integration, no dedup. Skill pack is
purely orthogonal domain.

## Recommendation

**Defer** — revisit only if jarvis-trader adds an autonomous ML research
loop (e.g., RL strategy discovery leveraging DSPy). At that point, the
`autoresearch` orchestrator would be the single integration candidate.

## Effort

Current: **none**. Future (if autoresearch loop lands): **M** (port
`autoresearch` skill adapted for strategy discovery, ~8h).

## Red flags

- None for current scope. Well-maintained, MIT, actively pushed. Simply
  not applicable to the current product.
