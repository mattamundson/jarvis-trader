# JARVIS Research Note — sunday-quant-scientist (mattamundson/sunday-quant-scientist)

**Source:** `mattamundson/sunday-quant-scientist`, default branch `main`, 71 files, fork (archived: no, private: no), pushed 2025-09-20.
**What it is:** A free newsletter for quantitative/algo trading, portfolio analysis, and investing — ships as a set of numbered script demos (QS001–QS007+).

## Reusable patterns for JARVIS

### 1. Numbered demo-script index as a learning/onboarding ladder
- The repo is a sequence of self-contained demo scripts, each teaching one concept (OpenBB financial data, automate-trades, stock screener, EMA, pytimetk, anomaly buy/sell, ML trend detection). This is a **learning ladder** pattern.
- JARVIS strategy research docs can adopt the same pattern for onboarding: a numbered sequence of "concept → minimal reproducible script/notebook → what it teaches" entries under `docs/research/strategy-research-onboarding.md`. This is a doc structure, not a code import.

### 2. OpenBB as a market-data adapter reference
- Several demos use OpenBB as a free market-data gateway. JARVIS' audit already flags market-data adapters; OpenBB is a concrete free-tier reference point. The JARVIS add is to note OpenBB as a **candidate free data adapter** in the market-data tooling index, with the caveat that free adapters have freshness/scope limits and must not be the sole source for any live decision.

### 3. "Avoid algo trading mistakes" as a critique checklist seed
- QS004 is literally titled "avoid algo trading mistakes." This is a seed for the JARVIS backtest critique checklist — the checklist should include a "common algo trading mistakes" section drawn from the quant community's known failure modes (look-ahead, overfitting, survivorship, transaction cost neglect, regime shift).

### What NOT to import
- The individual demo scripts are educational, not production-grade. Do not vendor them into JARVIS engine code.
- No execution wiring; no risk limit changes.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/strategy-research-onboarding.md` — numbered learning-ladder structure + OpenBB as a free-data adapter reference + seed for the backtest critique checklist's "common mistakes" section.

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
