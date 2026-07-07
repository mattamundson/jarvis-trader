---
repo: google-ai-edge/gallery
url: https://github.com/google-ai-edge/gallery
stars: 21313
language: Kotlin
license: Apache-2.0
archived: false
pushed_at: 2026-04-17T00:14:39Z
analyzed_at: 2026-04-17
recommendation: no-fit
surfaces_with_value: []
---

# google-ai-edge/gallery

## Core value proposition

Mobile app (Kotlin/iOS) showcasing on-device generative AI via LiteRT runtime. Features model download/testing, multimodal chat with thinking-mode reasoning, audio transcription, and local LLM inference with zero internet dependency. Latest release adds Gemma 4 support.

## Surface analysis

### 1. Engine code
**no-fit** — Gallery is a mobile/app framework for LLM experimentation, not a trading strategy module. No signals, risk controls, execution logic, or market data pipelines applicable to jarvis-trader's futures trading engine. Kotlin → Python incompatibility.

### 2. Project rules
**no-fit** — No applicable coding discipline, safety invariants, or testing patterns. Mobile app development rules (UI state, Kotlin coroutines, permission models) do not transfer to FastAPI/agent workflows.

### 3. Project skills
**no-fit** — Agent Skills in Gallery (Wikipedia grounding, maps, visual summaries) are mobile-specific presentation layers. Jarvis-trader agents operate on market data, regime detection, and trade signals—different problem domain.

### 4. Slash commands
**no-fit** — Gallery's feature surface (model selection, chat toggle) is UI-driven. Jarvis-trader commands operate on portfolio state, backtests, and alerts.

### 5. Subagents
**no-fit** — Gallery's reasoning layer (Gemma thinking mode) is LLM introspection, not trade decision-making. No advisor pattern, debate structure, or market regime intelligence.

### 6. Docs
**no-fit** — Wiki and development notes focus on app build, model download, and on-device runtime tuning. Jarvis-trader docs cover trading logic, backtest methodology, and execution safeguards.

### 7. Dev tooling
**no-fit** — Build system is Kotlin/Gradle, not Python/pnpm. Mobile CI/CD and on-device benchmarking patterns do not overlap with FastAPI test harness or PM2 orchestration.

### 8. Dashboard
**no-fit** — Gallery UI shows chat history, model selector, parameter dials. Jarvis-trader dashboard monitors positions, P&L, regime, and signal strength across instruments. Completely different information model.

### 9. Ops / messaging
**no-fit** — Gallery notifications are model-download prompts and debug logs. Jarvis-trader ops are trade approvals, risk alerts, and market state broadcasts. No overlap in alert semantics.

## Integration plan

No integrations. Recommend classify as **noise** — valid repo in its domain (mobile GenAI), zero intersection with futures trading pipeline. No code reuse, no architectural patterns, no operational lessons applicable to jarvis-trader.

## License & attribution

Apache 2.0. License is permissive but integration not applicable.

## Effort estimate

S (N/A for integration)

## Red flags

- **Domain mismatch**: Mobile app framework vs. headless trading engine. Different runtime (Kotlin/JVM vs. Python), different deployment target (user devices vs. server), different data model (chat/images vs. market prices/orders).
- **No trading relevance**: LLM reasoning on arbitrary topics bears no relation to market microstructure, regime detection, or position sizing.
- **Technology stack**: Kotlin ↔ Python incompatibility rules out any code borrowing.
