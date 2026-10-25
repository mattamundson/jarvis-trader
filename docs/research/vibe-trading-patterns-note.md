# Vibe-Trading patterns note — from `mattamundson/Vibe-Trading`

**Source:** `mattamundson/Vibe-Trading` (reference fork, 1633 files, public)
**Date mined:** 2026-09-28
**Scope:** research note / patterns reference. No code vendored. No execution wiring.

---

## What it is

Vibe-Trading: "Your Personal Trading Agent" — a large Python trading agent framework: FastAPI backend, React frontend, 7 backtest engines (ChinaA, GlobalEquity, Crypto, ChinaFutures, GlobalFutures, Forex, OptionsPortfolio), 18 market-data loaders, 79 skills, 29 multi-agent swarm teams, a Shadow Account self-mining loop, and a pre-trade advisory interface.

This note extracts the *patterns* that transfer to JARVIS, not the catalog. Vibe-Trading is a different product (multi-asset, China A-shares, crypto, options) and JARVIS should not try to match its breadth.

---

## Pattern 1 — Pre-trade advisory interface (highest-value takeaway)

**Source:** `agent/src/live/advisory/` in the Vibe-Trading tree.

This is the single most directly reusable artifact. It's a broker-agnostic, fail-open, default-off advisory layer that produces an observational risk verdict on a proposed order *without ever blocking execution*. The mandate gate remains the sole authority for order allow/deny.

### Design

- **`Verdict` enum:** `APPROVE` / `APPROVE_WITH_CONCERNS` / `REJECT` / `REVIEW_UNAVAILABLE`
- **`AdvisoryContext` dataclass:** carries the order context the advisory layer needs (symbol, side, size, price, account state, etc.)
- **Fail-open:** any provider exception → `REVIEW_UNAVAILABLE`, order proceeds. The advisory layer is observational; it never becomes the bottleneck that stops trading.
- **Default-off:** controlled by `VIBE_TRADING_ENABLE_ADVISORY` — the advisory layer is off by default and must be explicitly enabled.
- **Broker-agnostic:** no broker-specific logic in the advisory layer; it receives an abstract order context and returns a verdict.
- **Audit-embedded:** the verdict goes into `gate_decision["advisory"]` so every order carries its advisory review as auditable context.

### Why it matters for JARVIS

JARVIS' engine safety layer already has the advisory-vs-enforcement distinction conceptually, but Vibe-Trading makes it *explicit as a pluggable interface*. The `REVIEW_UNAVAILABLE` sentinel and the "fail-open, audit-embedded" design are directly transferable patterns. If JARVIS ever adds an advisory layer (e.g. a discretionary-overlay agent that reviews orders before the mandate gate), this is the reference design: default-off, fail-open, audit-embedded, broker-agnostic, mandate-gate-respecting.

---

## Pattern 2 — Futures multiplier-aware PnL / margin / sizing abstraction

**Source:** `agent/backtest/engines/futures_base.py` in the Vibe-Trading tree.

Clean abstraction for futures position sizing:

- **PnL:** `direction × size × multiplier × (exit − entry)`
- **Margin:** `size × price × multiplier / leverage`
- **Sizing:** `target_notional / (price × multiplier)`
- **`get_contract_multiplier(symbol)`** — per-symbol multiplier lookup

JARVIS' existing execution/risk code already handles MES contract specs, but the Vibe-Trading pattern is a reference for how to structure multiplier-aware sizing so it's *testable per-symbol*. The key improvement over ad-hoc sizing is: the multiplier is an explicit, looked-up value, not a hardcoded constant buried in a formula. This makes it easy to add a new instrument (e.g. a different futures contract) by adding its multiplier to the lookup rather than rewriting sizing logic.

---

## Pattern 3 — Shadow Account self-mining loop

**Source:** `agent/src/live/shadow_account/` in the Vibe-Trading tree.

Workflow: upload broker export → analyze behavior → extract 3–5 rules → backtest → render report → scan today's signals.

This is a "mine your own trading history for explicit rules" workflow. It turns realized trade history into a candidate rule set, backtests it, and surfaces whether those rules would have helped. JARVIS doesn't have an equivalent today — it's a candidate feature for the journal/analytics side, not the execution side. The value proposition: if you've been trading for a while, your own history contains patterns you haven't formalized; this loop extracts them.

---

## Pattern 4 — The "kitchen sink" cautionary tale

Vibe-Trading has 79 skills, 452 alphas (Alpha Zoo), 7 backtest engines, 29 swarm teams, 18 data loaders. This is a *lot* of surface area. The lesson for JARVIS: Vibe-Trading is a different product with a different mandate (multi-asset, global, retail-facing). JARVIS should not try to match its breadth. The distillation is the *patterns* (advisory interface, multiplier-aware futures, shadow account), not the catalog.

---

## What JARVIS should borrow

1. **Pre-trade advisory interface design** — the `Verdict` enum, fail-open behavior, default-off switch, broker-agnostic context, and audit-embedded verdict placement. This is the most actionable pattern for the engine's safety layer if an advisory overlay is ever added. Reference design, not a mandate.

2. **Futures multiplier-aware sizing abstraction** — explicit per-symbol multiplier lookup, separate PnL/margin/sizing formulas that use it. A reference for how to structure sizing so new instruments are additive (add a multiplier) rather than invasive (rewrite a formula).

3. **Shadow Account loop as a future journal feature** — a candidate for the journal/analytics side: formalize rules from realized history, backtest them, see if they help. Not an execution feature.

---

## What JARVIS should NOT borrow

- **No skill/alpha catalog.** 79 skills and 452 alphas is Vibe-Trading's product breadth, not JARVIS' mandate. Exclude.
- **No multi-asset engine sweep.** 7 backtest engines across ChinaA, GlobalEquity, Crypto, ChinaFutures, GlobalFutures, Forex, OptionsPortfolio — JARVIS is MES futures. Exclude.
- **No swarm team architecture.** 29 multi-agent swarm teams is a different agent paradigm than JARVIS' pipeline. Exclude.
- **No data loader catalog.** 18 market-data loaders is Vibe-Trading's data surface. JARVIS has its own feed adapters (Databento, IBKR, yfinance, FRED). Exclude.
- **No execution wiring.** The advisory interface is *observational only* by design — it never blocks execution. Any JARVIS advisory layer must preserve that property. The shadow account loop is analytics-only.

---

## Verification

- File-tree census and content extraction read back from GitHub API / raw.githubusercontent.com before writing.
- No fork default branch modified.
- `gh repo view` confirms `mattamundson/Vibe-Trading` is `isFork: true`, `isArchived: false`, `visibility: PUBLIC`, topics `reference, trading-research, vendor-fork`.
- Advisory interface, futures base engine, shadow account, and skill manifest were read; the remaining 1633-file tree was not exhaustively mined (per the audit's "distilled docs over vendoring large forks" rule).

---

*This note distills patterns from a reference fork for JARVIS' safety-layer and sizing documentation. It is not a trading strategy, not an execution surface, and not a recommendation to deploy Vibe-Trading's agent swarm or alpha catalog in JARVIS.*
