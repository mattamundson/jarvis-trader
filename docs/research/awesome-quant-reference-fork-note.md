# JARVIS Research Note — awesome-quant (mattamundson/awesome-quant)

**Source:** `mattamundson/awesome-quant`, default branch `main`, 52 files, fork (archived: no, private: no), pushed 2026-09-12.
**What it is:** A curated Awesome list of quant libraries/packages/resources.

## Reusable patterns for JARVIS

### 1. Reference-fork hygiene model (the list itself IS the pattern)
- This repo is literally a canonical "here are the dependencies a quant stack should know about" index.
- JARVIS already does this implicitly via `docs/research/REPO_CONSOLIDATION_INVENTORY_*.md` and the audit. The pattern to absorb: make the **strategy research tooling index** an explicit, maintained doc — a living `docs/research/strategy-research-tooling.md` that catalogs: data adapters, backtest engines, execution brokers, risk monitors, observability, and the JARVIS-native choice for each with rationale.
- This is a doc governance pattern, not a code import.

### 2. Category structure worth mirroring
The list is organized by function (data, backtesting, execution, risk, viz, ML, etc.). JARVIS strategy docs can adopt the same functional taxonomy so a new strategy author knows which layer they're working in:
- data acquisition / market data
- signal generation / alpha
- backtest / validation
- paper/live execution
- risk & drawdown controls
- observability & journal

### What NOT to import
- The list itself is large and opinionated; do not vendor it. Do not pin JARVIS to any specific third-party tool a quant list recommends without a JARVIS owner reviewing it.
- No execution wiring; no risk limit changes.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/strategy-research-tooling.md` — one table, functional category → JARVIS-native tool/approach + rationale + "do not use without review" notes.
- Closes the "keep as reference fork" disposition by converting the reference's value (a curated index) into a JARVIS-native index.

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
