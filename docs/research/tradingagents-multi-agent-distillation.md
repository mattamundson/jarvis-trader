# TradingAgents multi-agent architecture distillation

Status: research/control artifact only. No live trading config, paper trading
config, risk limits, kill-switch state, broker routing, API keys, `.env` files,
PM2, active instrument gates, scheduled tasks, or order behavior are changed.

## Source mined

- Reference repo: `mattamundson/TradingAgents`
- Reference commit: `904071b` (v0.4.0)
- Source role: multi-agent LLM financial trading framework (TauricResearch)
- Selected files reviewed:
  - `README.md` (architecture overview, analyst/researcher/trader/risk teams)
  - `tradingagents/graph/trading_graph.py` (orchestration, LangGraph-based)
  - `tradingagents/agents/risk_mgmt/` (aggressive/conservative/neutral debators)
  - `tradingagents/graph/propagation.py`, `reflection.py`, `conditional_logic.py`
  - `tradingagents/schemas.py` (decision schemas)

## Coverage proof

PR #894 (wave2 trading-leverage-docs, CLOSED) and PR #834 (Sunday Quant
Scientist, MERGED) already cover regime features and quant tooling. This repo
adds a different non-duplicative control: **a reference multi-agent architecture
where specialized LLM agents debate before a risk team approves execution.**

JARVIS has the pipeline/run architecture and strategy registry. TradingAgents
shows an alternative decomposition: analyst team → bullish/bearish researchers
→ trader → risk management → portfolio manager. Each role is a separate agent
with a defined input/output contract.

## Transferable findings

### 1. Role-separated agent architecture

TradingAgents decomposes trading into specialized roles that pass structured
outputs between them:

| Role | Responsibility | JARVIS analog |
|---|---|---|
| Fundamentals Analyst | Financials, red flags, intrinsic value | Strategy registry hypothesis review |
| Sentiment Analyst | News, StockTwits, Reddit sentiment aggregate | Discord/Twitter bias feed (existing) |
| News Analyst | Global news + macro indicators | FRED/macro regime context (existing) |
| Technical Analyst | MACD, RSI, pattern detection | chart-review-runbook (existing) |
| Bullish Researcher | Critically assess bullish cases | adversarial_reviewer class (existing) |
| Bearish Researcher | Critically assess bearish cases | adversarial_reviewer class (existing) |
| Trader | Compose reports, timing + magnitude | pipeline/run decision layer |
| Risk Management | Volatility, liquidity, strategy adjustment | risk_advisory class (existing) |
| Portfolio Manager | Approve/reject proposed trade | gate-v2 routing decision |

The key architectural insight: **separate agents debate before any decision
reaches execution.** JARVIS's pipeline already has stages; TradingAgents adds
the pattern of having multiple independent agents evaluate the same candidate
from different perspectives before a risk gate decides.

### 2. Structured debate with reflection

TradingAgents uses a LangGraph-based graph with:
- **Propagation**: agents pass findings forward through the graph
- **Reflection**: a reflector agent reviews the accumulated evidence
- **Conditional logic**: graph routing based on intermediate results
- **Checkpointing**: state persisted so runs can resume after interruption

The reflection step is the most transferable pattern: an agent that reviews
what the other agents produced, looking for gaps, contradictions, or overconfidence.

### 3. Risk management as a separate team, not a gate

In TradingAgents, risk management is a *team of agents* (aggressive, conservative,
neutral debators) that evaluates risk from multiple perspectives and *reports* to
the Portfolio Manager. The Portfolio Manager makes the final approve/reject call.

This is different from JARVIS's current gate-v2 approach (binary routing decision).
The TradingAgents pattern suggests: **risk advisory should be multi-perspective,
not single-threshold.** A conservative debator, an aggressive debator, and a
neutral debator each write a short assessment; thePortfolio Manager (or JARVIS's
gate-v2) weighs them.

### 4. Point-in-time data integrity

TradingAgents v0.4.0 specifically fixed look-ahead bias in FRED macro data and
social sentiment. The fix: use `realtime_start` (first date the value was known)
not `effective_date` for point-in-time integrity. This matches the fix already
applied to `macro-regime-context-spec.md` via PR #919.

### 5. Decision log as audit trail

TradingAgents maintains a persistent decision log (memory) that records each
agent's contribution and the final decision. JARVIS's pipeline already produces
run artifacts; TradingAgents adds the pattern of a structured decision log that
ties each decision back to the agent contributions that produced it.

## JARVIS-relevant distillation

### What to add to JARVIS docs

1. **Multi-agent review pattern for strategy registry**
   - When a strategy candidate reaches the review stage, an adversarial_reviewer
     agent should produce both a bullish and bearish assessment before the
     gate-v2 verdict. This is the TradingAgents "bullish/bearish researcher"
     pattern applied to JARVIS strategy promotion.

2. **Reflection agent for backtest critique**
   - After a backtest report is generated, a reflection agent reviews it for
     common failure modes (overfit, lookahead, survivorship, regime mismatch)
     before the critique checklist is applied. The checklist (existing) is the
     structured list; the reflection agent is the contextual reviewer.

3. **Multi-perspective risk advisory**
   - Instead of a single risk_advisory output, produce three: conservative,
     neutral, and aggressive assessments of the same candidate. The gate-v2
     decision layer weighs all three. This mirrors the TradingAgents risk
     management team structure.

### What NOT to vendor

- The full TradingAgents agent runtime (LangGraph, 167 files) — too large,
  different execution model, not adapted to JARVIS's pipeline architecture.
- The yfinance/Alpha Vantage data connectors — JARVIS uses Databento/IBKR.
- The Polymarket data vendor — different asset class.
- The specific LLM provider registry — JARVIS has its own LLM client layer.

### Acceptance criteria for any future TradingAgents-derived JARVIS feature

1. Source repo and commit cited.
2. Pattern distilled as a doc/architecture note, not vendored code.
3. Any agent role added to JARVIS must declare its authority class (from
   `claude-trading-skills-intake-gate.md`): research_context, candidate_generator,
   adversarial_reviewer, risk_advisory, or operator_checklist.
4. Multi-agent debate outputs must be structured artifacts (JSON/YAML), not
   free-text, so they can be audited and replayed.
5. Point-in-time data integrity must use `realtime_start` for any macro/sentiment
   data, matching the existing `macro-regime-context-spec.md` guard.
6. Decision log entries must tie back to specific agent contributions for audit.

## Source manifest

- `mattamundson/TradingAgents` default branch `main`, tree `904071b`, 167 files
- Selected files: README.md, tradingagents/graph/trading_graph.py,
  tradingagents/agents/risk_mgmt/aggressive_debator.py,
  tradingagents/agents/risk_mgmt/conservative_debator.py,
  tradingagents/agents/risk_mgmt/neutral_debator.py,
  tradingagents/graph/propagation.py, tradingagents/graph/reflection.py,
  tradingagents/schemas.py
