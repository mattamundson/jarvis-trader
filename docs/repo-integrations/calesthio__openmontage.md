---
repo: calesthio/OpenMontage
url: https://github.com/calesthio/OpenMontage
stars: 2345
language: Python
license: AGPL-3.0
archived: false
pushed_at: 2026-04-13
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: []
---

# calesthio/OpenMontage

## Core value proposition

OpenMontage is an open-source, agentic video production system that automates end-to-end video creation (scripting, asset generation, composition, rendering). It uses 12 pipelines and 52 composable tools to produce video from plain-language prompts, via Claude, Cursor, Copilot, or other AI coding assistants. It supports both image-based animation (via Remotion, FFmpeg) and real-footage montage (via Archive.org, NASA, stock footage APIs). The system is designed for agent-driven orchestration: agents select pipelines, discover tools via a registry, and execute multi-stage workflows.

## Surface analysis

### 1. Engine code
**no-fit** — OpenMontage is a pure video production framework with no trading signals, backtesting, risk management, or portfolio execution. JARVIS TRADER has agent orchestration (`engine/agents/debate.py`, `managed_agent_bridge.py`, `pipeline.py`) but fundamentally different domain: financial decision-making vs. video composition. No tactical reuse exists.

### 2. Project rules
**no-fit** — OpenMontage rules would address video asset validation, pipeline determinism, and creative approval gates. JARVIS TRADER rules (`meta-discipline.md`, `safety.md`, `testing.md`) are trading-domain specific: invariants (stop-loss direction, trade state), safety boundaries (kill-switch, risk limits). Cross-domain contamination risk outweighs any reuse of general agentic discipline.

### 3. Project skills
**no-fit** — OpenMontage skills (pipeline stage direction, asset sourcing, composition staging) do not map to JARVIS TRADER workflows (morning brief, pretrade check, learning snapshot, WFE analysis). Video production and trading decision chains are distinct problem spaces.

### 4. Slash commands
**no-fit** — OpenMontage commands would be video rendering workflows. JARVIS TRADER commands (`jarvis-morning-brief`, `jarvis-pretrade-check`, `jarvis-kill-switch-check`) are pre-market, risk, and monitoring operations. No alignment.

### 5. Subagents
**partial-integrate** — OpenMontage uses agent-driven pipeline selection and stage execution. JARVIS TRADER already has specialized subagents (`backtest-runner`, `safety-reviewer`, `pipeline-debugger`). However, the *patterns* for how agents introspect available tools and select pipelines could inform future multi-path strategy selection in JARVIS (e.g., choosing between STC vs. ATR pipelines at runtime vs. startup). Requires design review: OpenMontage tool discovery assumes creative options; JARVIS has risk-gated execution paths. Not immediately integrable without architectural clarification.

### 6. Docs
**no-fit** — OpenMontage docs (`AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`, `PROVIDER.md`) address agent-to-video-tool mappings and pipeline manifests. JARVIS TRADER docs are trading runbooks, strategy architecture, and incident logs. Orthogonal domains.

### 7. Dev tooling
**no-fit** — OpenMontage uses `make setup`, `.env` for API key configuration, and Remotion/Node.js build steps. JARVIS TRADER uses pnpm, Python venv, PM2 ecosystem, and Anthropic SDK. Different tech stacks; no shared automation.

### 8. Dashboard
**no-fit** — OpenMontage dashboard would render video progress and composition previews. JARVIS TRADER dashboard monitors trades, positions, P&L, and regime signals. Entirely different monitoring axes.

### 9. Ops / messaging
**no-fit** — OpenMontage notifications would trigger on render completion, asset errors, or approval gates. JARVIS TRADER ops (`openclaw_notifier.py`, schedulers) are for market hours, kill-switch alerts, and trade execution milestones. No functional overlap.

## Integration plan

No integrations recommended at this time. OpenMontage and JARVIS TRADER are architecturally independent systems with no shared substrate: one orchestrates video production, the other orchestrates financial trading decisions. Superficial code reuse would introduce cross-domain contamination risk and maintenance burden without solving a blocking problem in either system.

## License & attribution

**AGPL-3.0** — Copyleft license requiring any derivative work to also be open-source under AGPL. Integration of OpenMontage code into JARVIS TRADER (a private trading system) is legally incompatible without either:
1. Releasing JARVIS TRADER as AGPL-3.0 open-source (not viable for proprietary trading strategy)
2. Licensing exception negotiation with OpenMontage authors
3. Reference-only, no code copy (acceptable; see red flags below)

**Action:** No code integration possible. Ideas only.

## Effort estimate

**Not applicable** — recommendation is defer pending legal/architectural clarification. If business case changes (e.g., "automate trade explainer videos"), re-scan with a dedicated legal/business review session. Effort for reference-only architectural study: S (< 2 hr).

## Red flags

1. **AGPL-3.0 license** — Copyleft; any code copy makes JARVIS TRADER derivative work, triggering disclosure requirements. This is a legal blocker, not a technical one. Mentioning ideas is safe; copying code is not.

2. **Domain mismatch** — OpenMontage solves video composition (creative, asset, timing). JARVIS TRADER solves financial execution (risk, timing, signal fusion). Orchestration metaphors are superficially similar but execution contexts are incompatible. Cargo-cult adoption of agent patterns without the financial risk framework would degrade system safety.

3. **Architectural dependency on Remotion + FFmpeg** — OpenMontage assumes Node.js (Remotion) + system FFmpeg. JARVIS TRADER is pure Python/Anthropic SDK. Adding these dependencies would bloat the engine for zero trading value.

4. **No trading value in any surface** — After cross-reference of all nine surfaces, zero trading signals, backtesting, risk, or execution patterns map to JARVIS. This is not a "will evaluate later" defer; it is a fundamental non-fit.

## Recommendation

**Classification: noise** (zero fit across all nine surfaces; AGPL license incompatibility). Archive this analysis and do not re-scan. If the user explicitly requests "build a tool to generate trade explainer videos," that is a new project (not JARVIS TRADER work) and would need its own business case, legal review, and stack decision.
