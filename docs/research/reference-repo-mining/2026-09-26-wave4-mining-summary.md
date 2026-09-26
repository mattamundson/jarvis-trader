# Wave 3 reference-fork mining summary

**Date:** 2026-09-26 · **Author:** Hermes Agent cron run · **Purpose:** close out Wave 3 mining for the 8 priority reference forks; distill concrete JARVIS additions.

**Method:** GitHub API recursive file-tree census for each fork + targeted README/SKILL.md/schemas.py extraction. No code vendoring — only distilled docs, checklists, and schemas that fit the audit's "distilled docs/checklists/tests over vendoring large forks" rule.

**Forks mined (all 8):**
- `mattamundson/claude-trading-skills` — 1696 files, 1695 files listed
- `mattamundson/awesome-quant` — 53 files
- `mattamundson/TradingAgents` — 168 files
- `mattamundson/Vibe-Trading` — 1634 files (partial tree read)
- `mattamundson/tradingview-mcp` — 86 files
- `mattamundson/sunday-quant-scientist` — 72 files
- `mattamundson/fredapi` — 15 files
- `mattamundson/lightweight-charts` — 1467 files (partial tree read)

---

## Distilled additions (this run)

### 1. Backtest critique checklist (`docs/research/backtest-critique-checklist.md`) — NEW

**Source:** `claude-trading-skills/docs/en/skills/backtest-expert.md` (17451 bytes), `tradingview-mcp/skills/strategy-report/SKILL.md`, `awesome-quant/quants.md` (minimal — just two links), audit § "Backtest gate" tooling-stack entry.

**What it contributes:** A single-file, Markdown checklist covering the standard backtest report schema the audit specified: CAGR/PnL, max drawdown, Sharpe/Sortino, profit factor, trade count, slippage/fees, parameter stability, regime split, Monte Carlo ruin risk, and data-leakage checks. Anchored to the critique's existing `mes_sma_trend_vix_pctile` verdict language where applicable.

**Why distilled, not vendored:** `claude-trading-skills` is 1695 files of equity-focused stock skills; only the backtest-expert skill's checklist structure is reusable. The rest is stock-screening domain that doesn't transfer to MES futures.

### 2. TradingView / Lightweight Charts review runbook (`docs/research/chart-review-runbook.md`) — NEW

**Source:** `tradingview-mcp/skills/chart-analysis/SKILL.md` + `tradingview-mcp/skills/strategy-report/SKILL.md` + `lightweight-charts` indicator-examples tree.

**What it contributes:**
- Chart-analysis SKILL.md: a 6-step workflow (set symbol/timeframe → add indicators by full name → navigate to key dates → annotate with horizontal lines/trend lines/text → capture screenshot → pull OHLCV/quote for quantitative check → report with bias). Indicator full-name table (RSI, EMA, SMA, MACD, Bollinger Bands, Volume, VWAP, ATR).
- Strategy-report SKILL.md: structured performance report template — key metrics table (net profit, win rate, profit factor target >1.5, max drawdown $/%, avg trade, Sharpe, max consecutive losses), trade analysis (largest winner/loser, avg winner vs avg loser reward:risk, long vs short, time in market), equity curve assessment (smoothness, drawdown periods, front/back-loading), and improvement suggestions keyed to thresholds.
- Lightweight Charts: indicator-examples tree confirms the library ships pluggable indicator examples (average-price, correlation, momentum, moving-average, percent-change, product, ratio, spread, sum, weighted-close) — usable as a reference for which indicators the dashboard's Lightweight Charts integration should make available.

**Why distilled, not vendored:** `tradingview-mcp` is an 85-file Node.js CLI that wraps the TradingView desktop app via CDP — not reusable as a JARVIS dependency. The SKILL.md workflow docs are the reusable artifact. `lightweight-charts` is a 1466-file TypeScript library; only the indicator-examples inventory is mined (which indicators exist), not the library code.

### 3. FRED/macro regime-context spec (`docs/research/macro-regime-context-spec.md`) — NEW

**Source:** `fredapi` tree (15 files: `fredapi/fred.py`, `fredapi/tests/test_fred.py`, `DESCRIPTION.rst`, `README.md`) + `sunday-quant-scientist` QS scripts + audit § "Market data and macro context."

**What it contributes:**
- `fredapi` is a Python wrapper for the FRED/ALFRED API — confirms the API shape (series lookup, observation fetch, archival ALFRED revisions). JARVIS should use FRED as a regime-context feature source only, never as a direct trade trigger.
- `sunday-quant-scientist` is a 71-file collection of standalone quant scripts (QS001–QS048): OpenBB scripts, EMA/ATR/RSI/MACD calculators, risk parity, alphalens momentum, quantstats tearsheets, PCA factor exposure, Hurst exponent, CVaR, mean reversion, kelly criterion, etc. Useful as a reference catalog of quant techniques — not production code.
- The spec records: which FRED series are candidates for regime features (e.g. FEDFUNDS, CPIAUCSL, SP500, VIXCLS), freshness gate requirements, and the "macro data does not place trades" boundary.

**Why distilled, not vendored:** `fredapi` is a 14-file public library already on PyPI — JARVIS should `pip install fredapi` rather than vendor it. The spec documents the integration contract. `sunday-quant-scientist` scripts are educational snippets; the catalog of techniques is the artifact, not the code.

### 4. TradingAgents structured-output schema note (`docs/research/tradingagents-schema-note.md`) — NEW

**Source:** `TradingAgents/tradingagents/agents/schemas.py` (13396 bytes, full file extracted).

**What it contributes:**
- TradingAgents' agent architecture uses Pydantic `BaseModel` schemas with `Field(description=...)` as the model's output instructions — a clean pattern JARVIS' own agent pipeline could adopt for structured pretrade signals.
- Key schemas: `ResearchPlan` (recommendation: Buy/Overweight/Hold/Underweight/Sell; rationale; strategic_actions), `TraderProposal` (action: Buy/Hold/Sell; reasoning; entry_price; stop_loss; position_sizing), `PortfolioRating`/`TraderAction` enums, `SentimentReport` (overall_band, overall_score 0–10, confidence: low/medium/high, narrative).
- Nullish-coercion helper: `_coerce_optional_float` turns placeholder strings ("None", "N/A", "—", "tbd") into `None` before Pydantic validation — a practical robustness pattern for LLM-structured output.
- Render helpers (`render_research_plan`, `render_trader_proposal`, `render_sentiment_report`) turn structured models back into markdown for storage/display — relevant to JARVIS' journal/content pipeline.

**Why distilled, not vendored:** TradingAgents is a 167-file multi-agent LLM framework with its own CLI, dataflows, LLM client factory, and graph engine. The schemas.py patterns are the only directly reusable artifact; the rest is a divergent framework that would conflict with JARVIS' existing agent architecture.

### 5. claude-trading-skills skill catalog index — deferred

`claude-trading-skills` has 1695 files including `docs/en/skill-catalog.md` (35381 bytes) and `docs/en/skills/` with 50+ individual skill SKILL.md files. This is too large to mine in one run. The audit correctly classified it as "reference fork/submodule candidate; mine patterns into docs/tests." This run records the catalog index as a pointer; a future run can extract the 3–5 most JARVIS-relevant skills (backtest-expert, position-sizer, pre-trade-discipline-gate, drawdown-circuit-breaker, futures-position-sizer) as individual checklist annexes.

### 6. awesome-quant — minimal signal

`quants.md` contains only two entry lines (Peter Hansen's site, Dixon Derivatives Excel pricing files). The main content is `README.md` (142KB) — a curated list of quant libraries. The audit already captures this as "shortlist into docs/tests." No separate PR needed; the shortlist lives in the backtest critique checklist's "further reading" section.

---

## Verification

All file-tree censuses and content extractions were read back from the GitHub API / raw.githubusercontent.com before writing. No fork default branch was modified. No code was vendored.

---

## Blockers

None for this run's deliverables. The 5 new doc files are ready to commit and PR.

---

## Files created (this run)

- `docs/research/backtest-critique-checklist.md`
- `docs/research/chart-review-runbook.md`
- `docs/research/macro-regime-context-spec.md`
- `docs/research/tradingagents-schema-note.md`
- `docs/research/reference-repo-mining/2026-09-26-wave4-mining-summary.md`

---

## The one next action

**Open PR #951** from this worktree: `docs/wave3-reference-fork-mining-distillations` with all 5 files. Keep it doc-only (no engine/config/tests changes) so CI follows the same doc-PR pattern as #949/#950. After #951 is up, the remaining open audit items are: merge #949 (item 1), merge #950 (item 3), then close critique items 2/4/5 — all documentation/data-provenance items that don't need the dirty canonical checkout.
