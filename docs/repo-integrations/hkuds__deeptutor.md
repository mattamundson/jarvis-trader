---
repo: HKUDS/DeepTutor
url: https://github.com/HKUDS/DeepTutor
stars: 18761
language: Python
license: Apache-2.0
archived: false
pushed_at: 2026-04-15
analyzed_at: 2026-04-17
recommendation: dedup
surfaces_with_value: []
---

# HKUDS/DeepTutor

## Core value proposition
Agent-native personalized learning platform with multi-mode workspace (chat, quiz, research, tutoring), RAG-based knowledge bases, persistent memory, and 24+ LLM provider integrations. Targets educational use cases; not a trading system.

## Surface analysis

### 1. Engine code
**no-fit** — DeepTutor is built for educational personalization, not market microstructure. Core modules (tutoring flow, quiz generation, document RAG, guided learning journeys) have no direct analog in a futures trading engine. JARVIS TRADER already has a multi-agent debate system (debate.py + 10 analyst agents) and closed-loop learning via AgentFeedbackTracker. QuantAgent (HKUDS's prior work) inspired our Pattern Vision Analyst; DeepTutor does not add new trading signals or backtest harnesses.

### 2. Project rules
**no-fit** — DeepTutor's operational rules focus on LLM provider fallbacks, session persistence, WebSocket heartbeats, and knowledge base ingestion. JARVIS TRADER already manages these via TokenProxy (response caching, prompt compression), SessionManager (trade lifecycle), and LLM client (multi-provider auth). No novel discipline or safety invariant here.

### 3. Project skills
**no-fit** — DeepTutor's SKILL.md documents tutoring workflows (chat→quiz→research escalation), guided learning mode setup, and knowledge base management. These don't translate to trading workflows. JARVIS TRADER has domain-specific skills (backtest-report, agent-debate-explain, pm2-doctor, repo-integrator) and doesn't need a tutoring interface.

### 4. Slash commands
**no-fit** — DeepTutor CLI commands (`deeptutor kb upload`, `deeptutor chat`, `deeptutor quiz`) are for document management and interactive learning. JARVIS TRADER has `/pretrade-check`, `/engine-health`, `/backtest`, and `/briefing` — all trading-focused. No overlap.

### 5. Subagents
**no-fit** — DeepTutor uses subagents for quiz generation, answer explanation, research synthesis, and tutoring flow coordination. JARVIS TRADER's 10+ agents (bull_researcher, bear_researcher, technical_analyst, corey_auction_analyst, advisor_client, etc.) all consume market data and produce trading signals. Different problem domain.

### 6. Docs
**dedup-docs** — DeepTutor's educational architecture (multi-mode workspace, persistent memory, RAG pipeline) is documented in its README and architecture guides. JARVIS TRADER has equivalent runbooks in `docs/strategy/`, `docs/architecture/`, and `CLAUDE.md`. No new operational knowledge to carry over.

### 7. Dev tooling
**partial-fit** — DeepTutor's ecosystem highlights several tools worth observing:
- **24+ LLM provider abstraction**: Currently JARVIS TRADER routes through Anthropic + OpenAI fallback (engine/llm/client.py). DeepTutor's provider registry is more granular (DashScope, Qianfan, Groq, vLLM, local llama.cpp, etc.). Could inform future cost optimization if trading model usage expands beyond Sonnet/Haiku/Opus.
- **WebSocket heartbeat + auto-reconnect**: DeepTutor v1.1.0-beta added robust WebSocket lifecycle. JARVIS TRADER's OpenClaw notifier uses direct API calls, not persistent WS. Low priority; not a blocker.
- **Docker multi-arch images** (linux/amd64 + arm64): JARVIS TRADER runs on Windows WSL2 + local PM2. Docker is used for CI, not primary dev. No direct value.

**Classification**: `defer` — future cost-optimization spike could survey DeepTutor's provider abstraction as reference, but not actionable now.

### 8. Dashboard
**no-fit** — DeepTutor's Next.js 16 dashboard features: theme switcher (Snow, Glass), question notebook with bookmarks, quiz review UI, knowledge base file manager, chat composer with embedded search, visualize mode with Chart.js/SVG. JARVIS TRADER's dashboard (`dashboard/components/`) focuses on trade PnL, position monitor, regime indicator, signal heatmap, and backtester UI. No UI patterns or components to reuse.

### 9. Ops / messaging
**no-fit** — DeepTutor schedules cron jobs (session persistence, memory refresh, knowledge base indexing). JARVIS TRADER already has OpenClaw crons (morning brief 7am CT, pre-market news 8:30am CT, EOD 4pm CT, health check 30min). Trading-specific and orthogonal.

## Integration plan
No integrations. DeepTutor is a finished, self-contained educational platform with a different problem domain (personalized learning) than JARVIS TRADER (futures trading signals). While both are agent-native and multi-LLM, the architectural patterns are not portable:

- DeepTutor's RAG + knowledge base logic cannot be repurposed for market data pipelines (which are event-driven, low-latency, market-specific).
- DeepTutor's persistent user memory (learning history, preferences) is orthogonal to JARVIS TRADER's trade feedback loop (AgentFeedbackTracker).
- DeepTutor's tutoring agent collaboration patterns do not map to JARVIS TRADER's debate consensus (bull vs. bear scoring + advisor tiebreak).

**Recommendation**: classify as `dedup` (another agent-native multi-LLM system we've already shipped in different form) or `noise` if we're strictly trading-focused. Surfacing it was correct to verify; integration is not justified.

## License & attribution
Apache-2.0. No code integration required.

## Effort estimate
S (verification complete; no integration work)

## Red flags
- **Domain mismatch**: Educational tutoring system. JARVIS TRADER is a trading engine. Architectural similarities (agents, LLM abstraction, WebSocket, persistence) are superficial and not cross-applicable.
- **QuantAgent confusion**: HKUDS also publishes QuantAgent (the inspiration for our Pattern Vision Analyst). DeepTutor is a completely different codebase — do not confuse the two. QuantAgent = trading signals. DeepTutor = learning platform.
- **No trading signals or market integration**: DeepTutor does not consume market data, does not generate trade signals, has no backtest harness, and no order execution path. Even if modules were borrowed, they would require total reimplementation.
