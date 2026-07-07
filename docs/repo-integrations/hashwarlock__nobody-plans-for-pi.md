---
repo: HashWarlock/nobody-plans-for-pi
url: https://github.com/HashWarlock/nobody-plans-for-pi
stars: 26
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-03-30T16:47:45Z
analyzed_at: 2026-04-17
recommendation: dedup-skills
surfaces_with_value: []
---

# HashWarlock/nobody-plans-for-pi

## Core value proposition

Self-improving development workflows for the pi coding agent framework. Provides subagent orchestration, TDD enforcement, systematic debugging, and structured planning via workflows and skills — adapted from obra/superpowers but implemented as a native pi package using pi's subagent architecture.

## Surface analysis

### 1. Engine code
**no-fit** — Repository is TypeScript tooling for pi-agent framework, not trading logic. No signals, indicators, backtest harnesses, or risk checks applicable to futures trading engine.

### 2. Project rules
**dedup-rules** — Jarvis-trader already implements the planning/TDD/verification discipline in `.claude/rules/meta-discipline.md` and `.claude/rules/testing.md`. Nobody-plans-for-pi adds no new rule philosophy beyond what superpowers already established.

### 3. Project skills
**dedup-skills** — Superpowers v4.3.1 (already installed in Claude Code) provides all 13 core workflow skills: `brainstorming`, `writing-plans`, `executing-plans`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `using-git-worktrees`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `writing-skills`, `using-superpowers`. Nobody-plans-for-pi repackages these identical concepts for pi-agent instead of Claude Code.

### 4. Slash commands
**partial-dedup** — Nobody-plans-for-pi provides `/implement`, `/scout-and-plan`, `/implement-and-review`, `/review`, `/scout`. Superpowers triggers workflows via skill activation rather than explicit slash commands. Jarvis-trader uses both superpowers skills and custom `.claude/commands` (jarvis-morning-brief, jarvis-kill-switch-check, etc.). No new commands add value over superpowers + custom jarvis commands.

### 5. Subagents
**partial-dedup** — Nobody-plans-for-pi's subagent extension provides parallel/chain modes for pi-agent workers. Jarvis-trader uses Claude Code agents (backtest-runner.md, pipeline-debugger.md, safety-reviewer.md, memory-curator.md, dashboard-qa.md) via native Claude Code framework. Incompatible runtimes; no cross-compatibility.

### 6. Docs
**no-fit** — Documentation is pi-framework specific (how to install pi, override agent models, register custom agents). Not applicable to Claude Code workflow or jarvis-trader architecture.

### 7. Dev tooling
**no-fit** — Pi ecosystem tooling (`pi install`, `pi update`, agent definition files at `~/.pi/agent/agents/`). Jarvis-trader uses PM2 (ecosystem.config.js), GitHub workflows (.github/workflows/), Claude Code hooks (.claude/hooks/), and custom Python scripts (engine/scripts/). No pattern transfer.

### 8. Dashboard
**no-fit** — Repository contains no dashboard code. Tooling for pi agent only.

### 9. Ops / messaging
**no-fit** — No alert patterns, cron jobs, or message routes specific to futures trading or jarvis-trader's OpenClaw/WhatsApp notification layer.

## Integration plan

No integrations. Superpowers v4.3.1 is already shipping the structured planning, TDD, code review, verification, and debugging discipline that nobody-plans-for-pi reimplements for a different framework (pi-agent vs Claude Code).

**Recommendation**: Classify as `dedup-skills` and mark analyzed. The repo is valuable for teams adopting pi-agent, but jarvis-trader gains no new capability since superpowers already covers all nine surfaces.

## License & attribution

MIT. No code copy required; repo is a framework re-implementation for pi-agent, not a library.

## Effort estimate

S (no work required — already deduplicated by superpowers v4.3.1)

## Red flags

- **Framework mismatch**: Pi-agent runtime is incompatible with Claude Code. Nobody-plans-for-pi cannot be installed alongside superpowers in the same Claude Code session.
- **Unnecessary duplication**: Superpowers v4.3.1 already provides the entire methodology (brainstorm → plan → execute → review → verify pipeline with isolated subagents).
- **No new patterns**: Even the subagent modes (single, parallel, chain) map directly to superpowers' existing `dispatching-parallel-agents` and `subagent-driven-development` skills.
