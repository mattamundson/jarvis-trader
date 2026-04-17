---
repo: aaif-goose/goose
url: https://github.com/aaif-goose/goose
stars: 42375
language: Rust
license: Apache-2.0
archived: false
pushed_at: 2026-04-17T01:26:17Z
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [Engine code, Dev tooling, Ops / messaging]
---

# aaif-goose/goose

## Core value proposition

Goose is a general-purpose open-source AI agent framework written in Rust that provides a desktop app, CLI, and API for code and workflow automation. It integrates 15+ LLM providers (Anthropic, OpenAI, Google, Ollama) and 70+ extensions via Model Context Protocol (MCP), making it a flexible alternative or complement to single-provider agent frameworks. The architecture emphasizes provider-agnostic extension handling and native performance through Rust compilation.

## Surface analysis

### 1. Engine code

`defer` — Goose's agent-execution loop (task planning, tool dispatch, retry logic) and MCP extension framework are architecturally sound but would require a major refactor of `engine/agents/` to adopt. JARVIS-TRADER currently uses a Python-based debate/consensus pipeline with Anthropic-specific features (token tracking, cost attribution, prompt caching) and runs on sync FastAPI. Goose's async Rust design and multi-provider abstraction would conflict with existing orchestration. Value exists on the roadmap: Goose's MCP integration pattern is worth studying for post-paper-trading agent extensibility.

### 2. Project rules

`no-fit` — Goose's governance and coding discipline are orthogonal to trading systems. No LLM-discipline, safety invariant, or test patterns transfer directly.

### 3. Project skills

`no-fit` — Goose's CLI/desktop/API distribution model does not map to `.claude/skills/` (which are Claude Code workflows, not standalone tools).

### 4. Slash commands

`no-fit` — Goose's command vocabulary is agent-runtime operations; JARVIS-TRADER's commands are trading and analysis workflows.

### 5. Subagents

`defer` — Goose's distributed agent pattern (multiple concurrent workers, provider failover) aligns with JARVIS-TRADER's roadmap for multi-instrument parallel research (e.g., MCL + MNQ debate agents + sector rotation agent). Study value exists for async agent pooling and provider fallback orchestration, but integration requires: (a) Rust skill uplift (JARVIS currently Python-only engine), (b) IPC boundary definition (where Goose agents hand results back to Python pipeline), (c) provider key management (Goose uses ACP for transparent auth; JARVIS uses env vars). Blocked on architecture decision: embed Goose as library, shell out to CLI, or adopt Goose's design patterns only.

### 6. Docs

`no-fit` — Goose's installation, quickstart, and troubleshooting docs are for general AI agent users. JARVIS-TRADER's docs focus on trading rules, backtest results, and paper-trading operations.

### 7. Dev tooling

`partial-integrate` — Goose's build toolchain (Rust + Cargo, cross-compilation for macOS/Linux/Windows) and CI/CD setup are production-grade but orthogonal to current stack. However, Goose's ecosystem.config.js pattern for managing multiple distribution channels (desktop app, CLI, API) could inspire a future `ecosystem.config.js` refactor of JARVIS's PM2 setup. See `engine/ecosystem.config.js` (currently manages engine, dashboard, SDK pipeline only). Future value: study Goose's multi-binary distribution for custom goose distros (pre-configured providers, rules, extensions) as a model for a jarvis-trader-lite distribution (CLI-only, stripped-down API for paper-trading validation).

### 8. Dashboard

`no-fit` — Goose's desktop app is a generic agent UI (task history, tool invocation logs, provider selection). JARVIS-TRADER's dashboard is domain-specific (positions, signals, backtest snapshots, regime charts). No component reuse.

### 9. Ops / messaging

`defer` — Goose's cron/scheduler and alert integration patterns (notification backends) are generic. JARVIS-TRADER already has working WhatsApp/OpenClaw/Discord integration (`engine/notifications/openclaw_notifier.py`, `engine/schedulers/`). Study value on the roadmap: Goose's MCP notification server could abstract away platform-specific message formatting, but JARVIS's current inline rules (market hours gate, kill-switch validation) are tightly coupled to trading ops and would require significant refactoring.

## Integration plan

No immediate integrations. Three deferral pathways exist for future sessions:

1. **Multi-provider failover (T2 roadmap)**: Implement Goose's provider-fallback pattern (`anthropic` → `openai/gpt-4o` on 429) into `engine/llm/client.py`. Study: goose/providers/* for graceful degradation. Not a code port; a pattern adaptation.

2. **Distributed agent pooling (T3 roadmap)**: Post-paper-trading, evaluate Goose's concurrent-agent architecture for JARVIS's multi-instrument research layer. Decision required: Python+subprocess or native Rust integration.

3. **Custom distro + CLI (T4 roadmap)**: After live trading validation, Goose's custom-distro framework (`CUSTOM_DISTROS.md`) is a template for `jarvis-trader-lite` — a pre-configured CLI distribution with MCL/MNQ defaults, real API keys, and Anthropic-only provider (no fallback needed).

## License & attribution

Apache-2.0. No code integration planned, so no attribution needed yet. If pattern adaption proceeds, acknowledge in docstring: `# Adapted from aaif-goose/goose distributed-agent pattern`.

## Effort estimate

S (no immediate integration). If future integration occurs: `defer` pathway 1 = S, pathway 2 = L, pathway 3 = M.

## Red flags

- **Architectural mismatch**: Goose is Rust-native; JARVIS is Python-first. FFI/subprocess boundaries add operational complexity. MCP is the only bridge without rewriting the core engine.
- **Provider lock-in inversion**: Goose abstracts away provider differences; JARVIS deliberately locks to Anthropic for token tracking, prompt caching, and Opus consultancy. Multi-provider fallback could obscure signal quality degradation (ChatGPT produces different debate consensus than Claude).
- **Scope creep risk**: Goose's 70+ MCP extensions (Slack, GitHub, browser, file tools, etc.) are not trading-relevant. Integration without scope discipline could fragment agent focus.
- **Not yet battle-tested for trading**: Goose's agent loop has no built-in risk guards, kill-switch validation, or position invariant checks. Wholesale adoption would require hardening.
