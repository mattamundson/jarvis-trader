# Wave 4 reference-fork mining — vaulted run (Amo's personal machines, Hermes attached)

**Date:** 2026-09-28 · **Author:** Hermes Agent cron run · **Purpose:** close out the last three un-mined priority reference forks from the 2026-09-12 audit (`LLM-Trading-Lab`, `atlas-gic`, `Vibe-Trading`) and record the distilled JARVIS additions. This run was vaulted mid-flight because none of its outputs were committed, PR'd, or verified before Hermes re-entered.

**Method:** GitHub API recursive file-tree census + targeted README/architecture/schema extraction. No vendor code vendored; no live trading surfaces touched.

---

## Forks mined (3)

### 1. `mattamundson/LLM-Trading-Lab` — LLMs-as-portfolio-decision-makers experiment

**What it is:** A 6-month live experiment where ChatGPT (via structured weekly deep-research prompts) managed a real-money micro-cap equity portfolio (started ~$1M). 26 weekly research reports, full trade log, CSVs, and a formal evaluation paper.

**Source tree (relevant):**
- `Experiments/chatgpt_micro-cap/`
  - `trading_script.py` — execution harness (excluded; venue-specific)
  - `csv_files/Trade_Log.csv`, `Daily_Updates.csv` — realized trade record (excluded; raw data)
  - `collected_artifacts/deep_research_index.md` — master index of 26 weekly reports
  - `collected_artifacts/Weekly Deep Research (MD)/Week NN_Summary.md` — 26 weekly decision artifacts
  - `evaluation/paper.pdf` — formal evaluation (reference only)

**Distillation value for JARVIS:**

1. **Forward-only weekly research artifact structure** — every week produces a written summary *after* the week ends, covering thesis review, what worked, what didn't, risk re-rating, and position adjustments. This is exactly the "trading journal / weekly learnings" cadence the audit called out in `second-brain` as the canonical journal. JARVIS' dashboard journal and the `strategy-research-operating-model.md` post-trade/postmortem step should reference this as the exemplar structure.

2. **ChatGPT-as-portfolio-manager evaluation methodology** — the repo ships a formal evaluation paper (`evaluation/paper.pdf`). The key methodological lesson: if you ever let an LLM shape a portfolio, you need a pre-registered evaluation framework with realized-vs-expected comparison, not just narrative. JARVIS' `backtest-critique-checklist.md` already covers backtests; the LLM-lab pattern adds the "LLM decision audit" angle: log every LLM recommendation with timestamp, rationale, and forward outcome, then evaluate the decision process, not just the PnL.

3. **Micro-cap specific risk lessons** — the summary docs show the kind of position-level reasoning (catalyst tracking, stop re-rating post-catalyst, sell-the-news behavior) that a discretionary overlay needs. Not reusable as code, but useful as example text for JARVIS' trade-journal template.

**JARVIS disposition:** Reference fork; distilled pattern = "weekly forward-only research artifact + LLM decision audit log" → candidate addition to `docs/research/strategy-research-operating-model.md` (journal/postmortem section) and `second-brain` weekly-summary template. No code.

**Concrete doc to write (next run or handoff to Amo):** `docs/research/llm-decision-audit-pattern.md` — 1–2 pages: what the LLM-Trading-Lab experiment did, the weekly artifact structure, the recommendation-logging pattern, and how JARVIS' existing journal/gate/checklist infrastructure would absorb it. Mark as research-only; no execution wiring.

---

### 2. `mattamundson/atlas-gic` — self-improving AI trading agents (Karpathy autoresearch + Soros reflexivity + MiroFish)

**What it is:** A 4-layer multi-agent trading system: Layer 1 macro regime (10 agents: central bank, geopolitical, China, dollar, yield curve, commodities, volatility, emerging markets, news sentiment, institutional flow) → Layer 2 sector desks (7 sectors + relationship mapper) → Layer 3 "superinvestor" personas (Druckenmiller, Aschenbrenner, Baker, Ackman) → Layer 4 decision (CRO risk, alpha discovery, autonomous execution, CIO final). Agents are prompt-based; the autoresearch loop modifies prompts and keeps/reverts based on a 5-day Sharpe ratio.

**Source tree (relevant):**
- `architecture/overview.md` — 4-layer diagram + information flow
- `architecture/autoresearch.md` — self-improvement loop: identify worst agent → generate one prompt tweak → feature branch → 5-day trial → keep if Sharpe improved, git reset if not → repeat
- `architecture/layers.md` — layer responsibilities
- `prompts/` — agent prompts (excluded; proprietary prompts)
- `config/` — config (404 on direct read; structure inferred)
- `results/autoresearch_log.json` — 54 modifications, 16 kept, 37 reverted, 29.6% keep rate
- `results/summary.json` — period 2024-09-01 to 2026-03-07, 378 trading days, start $1M → end $940,938 (−5.91%), final agent weights
- `results/equity_curve.png` — excluded; image

**Distillation value for JARVIS:**

1. **4-layer regime→sector→persona→decision filtration** — this is a concrete multi-agent architecture that grounds each layer in a clear responsibility. JARVIS' existing agent pipeline (`engine/llm/`) is more linear; the atlas-gic layering is a useful reference for how to structure a discretionary-oversight multi-agent flow without every agent having execution authority. The CRO→CIO gating at layer 4 is especially relevant to JARVIS' risk/kill-switch discipline.

2. **Autoresearch keep/revert loop with git as the versioning mechanism** — the pattern: modify prompt → trial → measure → `git merge` if better, `git reset` if worse. This is a clean, auditable evolution loop that JARVIS could adopt for any prompt-based strategy component. The key safety property: every modification is either committed or reset; there's no drift. The 29.6% keep rate is honest — most tweaks don't help.

3. **Agent Sharpe as the loss function** — weighting recommendations by conviction, flipping sign for shorts, computing rolling Sharpe per agent, targeting the worst performer for modification. This is a concrete, defensible metric for "which agent needs attention." JARVIS' existing gate-v2 already computes similar metrics; the atlas-gic pattern shows how to drive agent improvement from them.

4. **The honest result: −5.91% over 378 days, 29.6% keep rate** — this is the most valuable distillation. A fancy 4-layer autoresearch system still lost money over 18 months. The keep/revert loop kept only 16 of 54 modifications. This is exactly the kind of "fancy research infrastructure does not guarantee profit" evidence that JARVIS' backtest critique and strategy registry should cite when resisting overengineering.

**JARVIS disposition:** Reference fork; distilled patterns = (a) layered multi-agent filtration architecture, (b) autoresearch keep/revert loop with git versioning, (c) per-agent Sharpe as improvement driver, (d) honest negative result as anti-overengineering evidence. No code; no prompts (proprietary).

**Concrete doc to write (next run or handoff to Amo):** `docs/research/atlas-gic-agent-architecture-note.md` — 2–3 pages: the 4-layer architecture diagram (text), the autoresearch loop, the per-agent Sharpe methodology, the 29.6% keep rate and −5.91% result as evidence, and a short "what JARVIS should and shouldn't borrow" section. The "shouldn't borrow" section is important: jarvis-trader already has deterministic gates; an autoresearch loop that modifies prompts based on live PnL would need its own safety review and should not touch the kill-switch or broker routing.

---

### 3. `mattamundson/Vibe-Trading` — personal trading agent (FastAPI + React + 79 skills + 7 backtest engines + shadow account)

**What it is:** A large (1633 files) Python trading agent framework: FastAPI backend, React frontend, 7 backtest engines (ChinaA, GlobalEquity, Crypto, ChinaFutures, GlobalFutures, Forex, OptionsPortfolio), 18 market-data loaders, 79 skills, 29 multi-agent swarm teams, a "Shadow Account" loop (upload broker CSV → analyze behavior → extract 3–5 rules → backtest → render report → scan today's signals), and a pre-trade advisory interface that's broker-agnostic and fail-open.

**Source tree (relevant, mined via git tree — 1633 files):**
- `agent/SKILL.md` — skill manifest (backtesting, factor analysis, Alpha Zoo 452 alphas, options pricing, 79 skills, 29 swarm teams, shadow account)
- `agent/api_server.py` — FastAPI server with Pydantic models for backtest metrics, auth, CORS
- `agent/backtest/engines/` — 7 engines; `futures_base.py` has contract-multiplier awareness (PnL = direction × size × multiplier × (exit−entry); margin = size × price × multiplier / leverage; sizing = target_notional / (price × multiplier))
- `agent/src/live/advisory/` — pre-trade advisory interface: `Verdict` enum (APPROVE / APPROVE_WITH_CONCERNS / REJECT / REVIEW_UNAVAILABLE), `AdvisoryContext` dataclass, fail-open (any provider exception → `REVIEW_UNAVAILABLE`, order proceeds), default-off (`VIBE_TRADING_ENABLE_ADVISORY`), broker-agnostic, audit-embedded (verdict goes into `gate_decision["advisory"]`). The advisory layer sits *outside* the mandate gate; the mandate gate remains the sole authority for order allow/deny.

**Distillation value for JARVIS:**

1. **Pre-trade advisory interface pattern (Vibe-Trading `agent/src/live/advisory/`)** — this is the single most directly reusable artifact. It's a broker-agnostic, fail-open, default-off advisory layer that produces an observational risk verdict on a proposed order without ever blocking execution. The mandate gate remains the sole authority. This maps almost 1:1 onto JARVIS' existing safety layer architecture (the engine's safety layer already has the "advisory vs enforcement" distinction; Vibe-Trading makes it explicit as a pluggable interface). The `REVIEW_UNAVAILABLE` sentinel and the "fail-open, audit-embedded" design are directly transferable patterns.

2. **Futures base engine contract-multiplier awareness** — `futures_base.py`'s `_calc_pnl / _calc_margin / _calc_raw_size` with `get_contract_multiplier(symbol)` is a clean abstraction for futuresポジション sizing. JARVIS' existing execution/risk code already handles MES contract specs; the Vibe-Trading pattern is a reference for how to structure multiplier-aware sizing so it's testable per-symbol.

3. **Shadow Account loop** — upload broker export → analyze behavior → extract rules → backtest → render report → scan today's signals. This is a "mine your own trading history for explicit rules" workflow. JARVIS doesn't have an equivalent; it's a candidate feature for the journal/analytics side, not the execution side.

4. **79 skills / 452 alphas / 7 engines** — this is a "kitchen sink" reference. The lesson for JARVIS: Vibe-Trading has a huge surface area and is a different product (multi-asset, China A-shares, crypto, options). JARVIS should not try to match its breadth; the distillation is the *patterns* (advisory interface, multiplier-aware futures, shadow account), not the catalog.

**JARVIS disposition:** Reference fork; distilled patterns = (a) pre-trade advisory interface (broker-agnostic, fail-open, default-off, audit-embedded), (b) futures multiplier-aware PnL/margin/sizing abstraction, (c) shadow-account self-mining loop as a future journal feature. No code vendored; the advisory pattern is the highest-value takeaway.

**Concrete doc to write (next run or handoff to Amo):** `docs/research/vibe-trading-patterns-note.md` — 2 pages: the advisory interface pattern (with the Verdict enum and fail-open design), the futures base engine multiplier abstraction, the shadow account loop, and a "what JARVIS should borrow" section that flags the advisory interface as the most actionable pattern for the engine's safety layer. Mark as research-only.

---

## What was NOT done (by design)

- No vendor code vendored, installed, or wired into engine/dashboard.
- No live/paper execution, risk limit, kill-switch, broker routing, `.env`, PM2, or scheduled task changed.
- `LLM-Trading-Lab` trade logs and `atlas-gic` prompts excluded — raw data and proprietary prompts are not reusable artifacts.
- `Vibe-Trading`'s full 1633-file tree was not exhaustively mined; only the advisory interface, futures base engine, shadow account, and skill manifest were read. The rest is a divergent multi-asset product.

---

## Verification

- All file-tree censuses and content extractions read back from GitHub API / raw.githubusercontent.com before writing.
- No fork default branch modified.
- `gh repo view` confirms all 3 forks are `isFork: true`, `isArchived: false`, `visibility: PUBLIC`, topics `reference, trading-research, vendor-fork`.

---

## Blockers

None for this run's deliverables. The 3 mining summaries are ready to be written as docs and PR'd, or handed to Amo for review.

---

## The one next action

**Write and PR the 3 distilled docs:**
1. `docs/research/llm-decision-audit-pattern.md` (from LLM-Trading-Lab)
2. `docs/research/atlas-gic-agent-architecture-note.md` (from atlas-gic)
3. `docs/research/vibe-trading-patterns-note.md` (from Vibe-Trading)

Keep it doc-only (no engine/config/tests changes) so CI follows the same doc-PR pattern as the prior wave. After this PR merges, every repo in the audit's "Vendor/reference forks to mine" list has either a distilled doc or an explicit "covered by existing doc / not worth separate doc" note — meaning the audit's mandatory mining items are complete.

Alternatively, if Amo wants to review these distillations before they're PR'd, hand off the summaries above and let him decide which (if any) become docs.
