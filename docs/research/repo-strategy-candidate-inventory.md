# Repo strategy and tool candidate inventory

This inventory separates **inventoried/mined** from **validated**. A row marked `reference only`, `needs data`, or `ready to backtest` is not validated alpha.

## Validation states

| State | Meaning |
|---|---|
| `validated-fail` | Has a JARVIS verdict or evidence artifact and failed/was halted. |
| `imported-reference` | Imported/mined into JARVIS docs/research, but not proven as a live strategy. |
| `ready-to-backtest` | Concrete enough to write or run a JARVIS backtest. |
| `needs-data-contract` | Requires data source/freshness/provenance before testing. |
| `reference-only` | Useful pattern/tool; do not treat as strategy evidence. |
| `separate-product` | Belongs primarily to another product and should bridge lessons only. |

## Current seeded registry entries

| Strategy | Source | Status | Evidence | Next action |
|---|---|---|---|---|
| `MES_trend_rank11` | `jarvis-trader` | `validated-fail` | `engine/research/strategy_registry/mes_trend_rank11.json` | Keep rejected until fresh honest gate-v2 PASS. |
| `MGC_trend_rank4` | `jarvis-trader` | `validated-fail/halted` | `engine/research/strategy_registry/mgc_trend_rank4.json` | Keep halted until fresh honest CORE PASS. |
| `MES_stc_trend_meta_rank1` | `jarvis-trader` | `validated-fail` | `engine/research/strategy_registry/mes_stc_trend_meta_rank1.json` | Do not route; mine failure features. |
| `SPY_stc_trend_meta_rank1` | `jarvis-trader` | `validated-fail` | `engine/research/strategy_registry/spy_stc_trend_meta_rank1.json` | Use as scanner-validation warning, not promotion evidence. |

## Candidate queue from repository estate

| Candidate | Source repo(s) | Type | Current status | Why it matters | Next validation step |
|---|---|---|---|---|---|
| Strategy registry seed entries from gate-v2 verdicts | `jarvis-trader` | research gate | `in progress` | Converts scattered verdict JSON into a visible promotion ledger. | Continue adding one entry per current/live risk relevant verdict. |
| LLM strategy iteration workflow + skill intake gate | `autotrade`, `claude-trading-skills` | agent workflow | `research-scaffolded` | Useful for ideation, critique, and manual discipline, but every skill output must declare authority class before influencing JARVIS. | Wave 29 adds an advisory-only trading-skill intake evidence gate; require backtest/registry gates before promotion. |
| Prompt-autoresearch risk controls | `atlas-gic` | agent workflow | `imported-reference` | ATLAS shows local prompt-metric improvement can coexist with negative campaign returns. | Require campaign-level economics and keep/revert receipts before any prompt mutation can affect promotion queues. |
| IBKR bootstrap notebooks | `jarvis-quant` | research workbench | `imported-reference` | Preserves learning/data access patterns without production imports. | Convert any reusable data access into a tested adapter spec. |
| Multi-agent market debate | `TradingAgents`, `Vibe-Trading` | agent workflow | `reference-only` | May improve research review, counterfactuals, and thesis critique. | Add a non-routing review prompt that critiques existing verdicts. |
| FRED macro regime context | `fredapi`, `sunday-quant-scientist`, `awesome-quant` | data/context | `needs-data-contract` | Regime filters can explain strategy decay and contextualize market briefs. | Define adapter contract, freshness SLA, and no-direct-trade boundary. |
| TradingView chart capture/review | `tradingview-mcp`, `lightweight-charts` | chart/review tool | `imported-reference` | Supports discretionary review, screenshots, and journal evidence. | Convert runbook into dashboard requirements and screenshot provenance. |
| Prediction-market probability normalization + replay evidence | `Polymarket-Trading-Bot`, `prediction-market-backtesting`, `polybot` | risk/probability pattern | `research-scaffolded` | Useful mental model for normalized probabilities, order-book imbalance, decision-time freshness, paired-leg inventory, and settlement-aware replay. | Wave 28 adds an offline event-market replay schema and `polybot` execution-risk evidence contract; no venue execution import. |
| Amo arbitrage forward-evidence bridge | `amo-arbitrage` | separate product bridge | `research-scaffolded` | Commodity/arbitrage lessons improve pre-registration integrity, forward-evidence tracking, single-writer feed provenance, and DQ fail-closed rules. | Wave 30 adds a bridge evidence contract; keep `amo-arbitrage` separate and do not import execution code. |
| Sentinel health/deadman probes | `jarvis-sentinel`, `home-scripts` | observability | `partially-covered` | Operational safety: feed freshness, PM2 leak checks, IB state, kill-switch state. | Consolidate into one home-scripts/JARVIS health probe contract. |
| Mission evidence schema | `jarvis-mission-control`, `master-jarvis` | orchestration | `covered` | Prevents workers from treating completion as acceptance. | Keep as master-jarvis authority; avoid duplicate runtime in JARVIS. |

## Rules for the next waves

1. No row becomes `paper_candidate`, `production_candidate`, or `approved` without a validated registry entry and human approval.
2. Reference forks are mined for ideas, not imported as operational dependencies.
3. Every strategy candidate must name a data source, feature family, backtest runner, artifact path, and blocking conditions before promotion.
4. Macro and charting tools can enrich review and journal context; they must not directly place trades.
5. Prediction-market tooling can contribute probability/risk ideas; venue-specific execution stays out of JARVIS futures routing.
