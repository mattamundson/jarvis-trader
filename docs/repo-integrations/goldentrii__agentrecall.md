---
repo: goldentrii/agentrecall
url: https://github.com/Goldentrii/AgentRecall
stars: 240
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-16T15:03:56Z
analyzed_at: 2026-04-17
recommendation: dedup
surfaces_with_value: []
---

# goldentrii/agentrecall

## Core value proposition

AgentRecall is a persistent session memory system with MCP server, TypeScript SDK, and CLI tools. It captures session insights, learns from corrections (Bayesian Beta feedback model), and recalls context across project boundaries. Core commands: `/arsave` (save session), `/arstart` (load context), `/arsaveall` (batch multi-session consolidation). Stores everything locally as markdown + Obsidian-compatible, with optional integration into LangChain/CrewAI/custom agents via SDK.

## Surface analysis

### 1. Engine code

**`dedup`** — No engine-specific signals, agents, backtesting infrastructure, or risk management that jarvis-trader needs. AgentRecall is purely a memory/awareness layer, not a trading system component. No fit.

### 2. Project rules

**`dedup`** — AgentRecall does not ship coding discipline, safety invariants, or testing patterns. The Intelligent Distance Protocol is a memory design philosophy, not an enforceable rule. No integration point.

### 3. Project skills

**`dedup-*`** — AgentRecall overlaps directly with existing infrastructure:
- `/arstart` command pattern → already implemented as `jarvis-trader/commands/jarvis-session-context.md` (cross-references agentrecall's design, confirmed in file header)
- Session handoff mechanism → already live at `jarvis-trader/docs/session-logs/handoff-*.md` (YAML + markdown format)
- Claude-mem MCP installed → provides cross-session symbol search + timeline context
- Obsidian integration → already wired via `obsidian-mind` skill at `~/.claude/skills/obsidian-mind/`

AgentRecall's MCP server is feature-complete but functionally equivalent to claude-mem's memory search (6 tools in AgentRecall vs. thedotmack's session transcript capture). **Recommendation: Reference the `/arsaveall` multi-agent pattern for future parallel-agent workflows** (jarvis-trader runs 10 parallel agents but currently issues `/arsave` N times, not once). No new code needed unless parallelizing session consolidation.

### 4. Slash commands

**`dedup-commands`** — `/arsave`, `/arstart`, `/arsaveall` patterns already exist:
- `jarvis-session-context.md` implements `/arstart` semantics (load handoff + git status + engine state)
- Handoff files auto-generated and pushed to GitHub (see memory.md: "auto-commits+pushes to GitHub on session end")
- No `/arsaveall` command exists — this would be novel for parallelized 10-agent consolidation, but is a polish item, not a blocker

### 5. Subagents

**`no-fit`** — AgentRecall defines no specialized analyzers or reviewers. Not applicable.

### 6. Docs

**`dedup`** — AgentRecall's session pattern is already documented in `jarvis-trader/docs/session-logs/roadmap-*.md`. The Intelligent Distance Protocol (gap navigation between human intent and AI action) is captured implicitly in trading decision logs and correction history in `jarvis-trader.db`. No documentation gap.

### 7. Dev tooling

**`no-fit`** — AgentRecall provides no CI/CD checks, PM2 patterns, GitHub Actions workflows, or hook automation. It's a runtime memory system, not a dev tool. No integration.

### 8. Dashboard

**`no-fit`** — AgentRecall is markdown + Obsidian compatible, not a web UI. jarvis-trader dashboard monitors live trades, not session memory. No overlap.

### 9. Ops / messaging

**`no-fit`** — AgentRecall has no notification, alert, or scheduling logic. No OpenClaw/WhatsApp/Discord integration. No fit.

## Integration plan

**No integrations.** Recommend classify as `dedup` (memory surface already covered by claude-mem + jarvis-session-context.md + handoff files).

**Future consideration:** If jarvis-trader deploys `/arsaveall` pattern for 10-agent parallel consolidation, reference `goldentrii/agentrecall` lines 79–119 for merge/dedupe semantics. The pattern is documented; adoption is a feature-request, not a codebase change.

## License & attribution

MIT. If any `/arsaveall` logic is adopted verbatim from AgentRecall, attribute in commit message as:
```
feat: parallel-agent session consolidation
Inspired by goldentrii/agentrecall /arsaveall pattern (MIT)
```

## Effort estimate

**N/A** — No integrations. If `/arsaveall` multi-agent pattern is later prioritized, estimate **S (2–4 hours)** for implementation.

## Red flags

- **Architectural redundancy:** claude-mem (already installed) provides session capture + timeline search; AgentRecall duplicates this at different abstraction layers (Bayesian Beta feedback vs. simple transcript indexing). Maintaining both adds mental overhead with diminishing returns.
- **Plugin-specific tool bloat:** AgentRecall MCP adds 6 tools to the MCP registry; they replicate claude-mem's search semantics. Each invocation adds gateway latency in OpenClaw. No performance gain.
- **Not production-critical:** jarvis-trader's existing `/arstart` command (jarvis-session-context.md) and handoff files already provide continuity. The correction-learning loop (Intelligent Distance) is aspirational but not operationally required for trading decisions.
