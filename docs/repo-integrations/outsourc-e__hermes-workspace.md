---
repo: outsourc-e/hermes-workspace
url: https://github.com/outsourc-e/hermes-workspace
stars: null
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-20T00:47:20Z
analyzed_at: 2026-04-18
recommendation: dedup
surfaces_with_value: []
---

# outsourc-e/hermes-workspace

## Core value proposition

Hermes Workspace is a native web UI for Nous Research's `hermes-agent` agentic framework. It provides real-time SSE chat streaming, memory/skills browsing, file terminal, PWA installation, 8-theme system, and Tailscale mobile access. Built for orchestrating Hermes agents in a local command center.

## Surface analysis

### 1. Engine code
**dedup-engine** — The supervisor pattern (agent message gating + marker state machine) is already ported to `engine/notifications/supervisor.py` (lines 1-45). Hermes Workspace's chat orchestration and event streaming architecture (SSE, tool call rendering) is UI-layer, not engine-applicable to futures trading.

### 2. Project rules
**no-fit** — No coding discipline or safety invariant patterns transferable.

### 3. Project skills
**no-fit** — Hermes Workspace is a workspace UI framework, not a reusable skill set.

### 4. Slash commands
**no-fit** — Commands are workspace navigation (`/chat`, `/memory`, `/skills`) not trading domain actions.

### 5. Subagents
**no-fit** — No specialized analyzers; workspace is a multiplexer for a single Hermes gateway.

### 6. Docs
**no-fit** — Setup and deployment docs (Docker, Ollama, Tailscale). Not operational runbooks for jarvis-trader.

### 7. Dev tooling
**defer** — PWA pattern + Tailwind 8-theme system + Monaco editor integration are solid. However, jarvis-trader already has `dashboard/components` + theme system. Reuse only if redesigning dashboard UX (not current priority).

### 8. Dashboard
**partial-integrate** — Hermes Workspace's theme infrastructure (light/dark variants, persistent theme selection) and file browser + terminal UI are high-quality. However, jarvis-trader's dashboard focuses on trading analytics (charts, positions, alerts), not agent interaction. Integration cost (React refactor + Monaco embedding) exceeds value for current roadmap.

### 9. Ops / messaging
**no-fit** — WhatsApp/Discord gateway integration patterns are orthogonal to jarvis-trader's notification supervisor.

## Integration plan

**No integrations recommended.** The supervisor pattern overlap (`engine/notifications/supervisor.py`) is already satisfied. Dashboard UI components are not mission-critical. Hermes Workspace is a complete UI framework for a different use case (agent command center); jarvis-trader's dashboard is trading-specific (positions, P&L, alerts).

## License & attribution

MIT — no compliance barriers if future dashboard redesign opts into Hermes theme patterns.

## Effort estimate

**N/A** — No integration proposed.

## Red flags

1. **Dedup risk (HIGH)**: `supervisor.py` already captures the load-bearing Hermes pattern. Importing Hermes Workspace code would duplicate agent-message-gating logic without adding trading value.
2. **Architectural mismatch**: Hermes Workspace is a general-purpose agent UI; jarvis-trader is a futures trading system. UI investment should follow domain priorities (P&L, risk, execution), not agent chat experience.
3. **Dependency drift**: Hermes Workspace depends on stock `hermes-agent` from PyPI + Node 22+. Adding as a dashboard choice requires dependency management and testing burden.

## Recommendation summary

**NOISE** — Defer indefinitely unless jarvis-trader's roadmap shifts toward agent collaboration UX. The supervisor pattern is already ported and sufficient. Dashboard themes can be adapted selectively if needed, but full Hermes Workspace integration is not a net-positive trade-off.
