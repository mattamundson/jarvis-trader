# JARVIS Research Note — TradingAgents (mattamundson/TradingAgents)

**Source:** `mattamundson/TradingAgents`, default branch `main`, 167 files, fork (archived: no, private: no), pushed 2026-09-01.
**What it is:** Multi-agent LLM financial trading framework (TauricResearch origin).

## Reusable patterns for JARVIS

### 1. Multi-agent role decomposition
- TradingAgents uses distinct agent roles (analyst, trader, risk, etc.) with a coordination protocol. JARVIS' existing strategy pages + agent commands already decompose work; the transferable pattern is the **role→responsibility→output contract** that TradingAgents encodes.
- JARVIS can absorb the pattern as a doc: `docs/research/multi-agent-role-contract-pattern.md` — each role has a single responsibility, a bounded output type, and an explicit handoff point. This reinforces (not replaces) JARVIS' existing safety layer / risk gating.

### 2. Environment/example file hygiene
- Ships `.env.example` and `.env.enterprise.example` — a clean pattern for separating shared config from environment-specific secrets. JARVIS already does this with `.env` gitignored; the transferable note is to keep the **example file as the single source of truth for field names/descriptions**, which JARVIS' existing pattern mostly does.

### 3. CLI onboarding visuals
- Ships CLI screenshots in `assets/cli/` — onboarding visuals for each command. JARVIS dashboard/docs can adopt the same "command → screenshot → one-line what-it-does" pattern for strategy pages and agent command docs, to reduce onboarding friction.

### What NOT to import
- Do not vendor the agent framework code. It targets a different stack/context and would not be a clean fit for JARVIS' existing engine/dashboard architecture.
- No execution wiring; no risk limit changes.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/multi-agent-role-contract-pattern.md` — role→responsibility→output contract pattern + handoff discipline, drawn from the multi-agent framework's structure (not its code).

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
