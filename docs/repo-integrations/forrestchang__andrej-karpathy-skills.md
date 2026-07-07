---
repo: forrestchang/andrej-karpathy-skills
url: https://github.com/forrestchang/andrej-karpathy-skills
stars: 50040
language: null
license: MIT
archived: false
pushed_at: 2026-04-15T17:47:20Z
analyzed_at: 2026-04-17
recommendation: dedup
surfaces_with_value: [rules]
---

# forrestchang/andrej-karpathy-skills

## Core value proposition

A single `CLAUDE.md` file distilling Andrej Karpathy's observations on LLM coding pitfalls into four principles: Think Before Coding (surface ambiguities, don't guess), Simplicity First (minimum viable code), Surgical Changes (touch only what you must), and Goal-Driven Execution (define success criteria before looping). Directly addresses LLM tendencies toward overcomplication, silent assumptions, and orthogonal refactoring.

## Surface analysis

### 1. Engine code
**no-fit** — The repo contains no trading strategies, indicators, backtesting harnesses, signals, or portfolio logic. Karpathy's discipline applies to *how* to build code, not *what* code to build for trading systems.

### 2. Project rules
**dedup-.claude/rules/meta-discipline.md** — The four principles from this repo were adapted and shipped in commit 966a2d3 as `.claude/rules/meta-discipline.md`. That file carries explicit attribution: "Adapted from Karpathy's LLM-coding observations via forrestchang/andrej-karpathy-skills (MIT)." File includes safety-critical guardrails tailored to jarvis-trader (MCL inverted-stop incident reference, kill-switch logic carveouts, surgical staging discipline due to parallel workstreams). Already integrated; no duplicate needed.

### 3. Project skills
**no-fit** — The repo does not contain reusable workflows, agent patterns, or multi-step orchestration. It is a single text file of principles, not a skill library.

### 4. Slash commands
**no-fit** — No `/pretrade-check`-style quick actions or command templates. The repo is discipline documentation, not a command interface.

### 5. Subagents
**no-fit** — No specialized analyzer or reviewer agents. Karpathy's principles apply to the *system prompt* of any agent (human or LLM), not as standalone subagents.

### 6. Docs
**no-fit** — The principles are already documented in `.claude/rules/meta-discipline.md`. No additional runbook, architecture note, or operational guide is needed beyond what already landed.

### 7. Dev tooling
**no-fit** — The repo contains no CI checks, PM2 patterns, pre-commit hooks, or automation. It is guidance, not tooling.

### 8. Dashboard
**no-fit** — No UI components, charts, or monitoring widgets. The repo is not frontend-adjacent.

### 9. Ops / messaging
**no-fit** — No alert patterns, cron jobs, or message routes. The discipline applies to how agents reason, not how alerts fire.

## Integration plan

No new integrations. The repository's entire value has already been captured and shipped in `.claude/rules/meta-discipline.md`. That file includes project-specific extensions (kill-switch carveouts, MCL stop-loss incident callout, surgical staging discipline for parallel workstreams) not present in the upstream Karpathy repo. Recommend classifying this repo as **dedup / fully integrated**.

## License & attribution

MIT license. Full attribution already present in `.claude/rules/meta-discipline.md` header (line 3):
```
_Adapted from Karpathy's LLM-coding observations via [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (MIT)._
```

## Effort estimate

S (already complete — integration shipped in prior session)

## Red flags

None. The repo is archived=false, actively maintained (pushed 2026-04-15), and MIT-licensed. No security or architectural concerns. The only "issue" is that the entire value already landed in `.claude/rules/meta-discipline.md` with proper attribution, so re-scanning this repo yields only confirmation that the prior integration is correct and complete.
