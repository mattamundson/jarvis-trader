# Discord Research Digest — Synthesis Index

_Generated 2026-04-17 from `C:\Users\mattm\discord-export\Jarvis-Trader - general [1490851279180660819].json` (353 messages → 97 unique trading-relevant items → deep README digest across 6 modules)._

## Scorecard

| Module | Items | Novel (actionable) | Dedup (already wired) | Noise |
|---|---:|---:|---:|---:|
| [strategy](strategy-synthesis.md) | 31 | **5** | 7 | 19 |
| [ml-ai](ml-ai-synthesis.md) | 31 | **3** | 4 | 24 |
| [data](data-synthesis.md) | 6 | 0 | 5 | 1 |
| [risk](risk-synthesis.md) | 3 | 0 | 0 | 3 |
| [execution](execution-synthesis.md) | 1 | 0 | 0 | 1 |
| [infra](infra-synthesis.md) | 1 | 0 | 0 | 1 |
| **Total** | **73** | **8** | **16** | **48** |

Raw item-per-module bundles: `C:\Users\mattm\discord-export\digest-raw\by-module\*.json`
Fetched READMEs (99 of 100 repos): `C:\Users\mattm\discord-export\digest-raw\github\*.md`

## What this tells you

- **8 genuinely actionable items out of 97.** ~8% signal. The other 92% is either already built into jarvis-trader or noise misclassified by the keyword-based triage.
- **The biggest dedup wins confirm existing architecture choices** — multiple third parties independently saved the same ideas Matt already shipped (weak-signals ensembling, GEX overlay, ORB signals, multi-agent debate, LangGraph orchestration, TradingView-over-CDP). That's corroboration, not redundancy.
- **The noise pile is dominated by** (a) Hermes agent ecosystem — competing runtime, would be a rewrite; (b) Polymarket — violates PRIMARY FOCUS DIRECTIVE (futures, not binary prediction); (c) generic AI tutorials misclassified as strategy/ml-ai.
- **Zero new data sources.** Existing TradingView + CDP + Reddit/PRAW + COT + ApeWisdom stack already covers what the community is sharing.
- **Risk classifier is broken** — 100% false-positive rate. Recommend tightening to require explicit risk-method terms (Kelly, VaR, CVaR, volatility targeting, etc.) instead of topic-adjacent words.

## Top 8 actionable items — ranked

| # | Module | Technique | Source | Touch point | Effort |
|---|---|---|---|---|---|
| 1 | strategy | MCL/MES/MNQ cointegration stat-arb | _(not from a single repo — gap confirmed)_ | `engine/strategies/` new module | medium |
| 2 | strategy | Taleb-persona tail-risk researcher in debate | `virattt/ai-hedge-fund` | `engine/agents/debate.py` + new `taleb_researcher.py` | small |
| 3 | ml-ai | GEPA prompt evolution with execution-trace feedback | `NousResearch/hermes-agent-self-evolution` | `engine/analytics/agent_feedback_tracker.py` + new optimizer | medium |
| 4 | strategy | Brier-score calibration on IC ensemble | `runesleo/polymarket-toolkit` | `engine/analytics/ic_ensemble.py` | small |
| 5 | ml-ai | Vision-based Pattern Agent (annotated charts) | `HKUDS/QuantAgent` | `engine/agents/technical_analyst.py` — new vision branch | medium |
| 6 | strategy | Optopsy options backtester | (Optopsy repo) | `engine/backtest/` new options harness | medium |
| 7 | ml-ai | Commission-aware PBR reward for RL trainer | TensorTrade | `engine/strategies/rl_environment.py` | small |
| 8 | strategy | Multi-strategy paper-trade competition harness | _(from multiple repos)_ | `engine/backtest/` new harness | large |

## How to execute

**Do not batch-implement.** For each item you pick:

1. Open the matching `<module>-synthesis.md` and read the full proposal (technique, risk, test sketch).
2. Branch off `main`: `git checkout -b digest/<slug>`.
3. Write the failing test first (per project standing TDD order).
4. Implement against the exact touch point listed — no ancillary refactoring.
5. Verify no backtest regression on MCL 1h + MNQ 1h (paper-approved symbols). MES can be excluded (WFE=0.09, already flagged).
6. One focused PR. Conventional commit.

## Classifier improvements for the next refresh

The daily scheduled task at 06:15 reruns `fetch_channel.py` + `triage_to_vault.py` + (manually) `digest_trading_links.py`. Before the next full synthesis pass, tune:

- **Risk classifier**: require one of `{Kelly, VaR, CVaR, Sortino, volatility targeting, risk parity, max drawdown, circuit breaker, trailing stop}` instead of the current loose match on "risk" / "sizing".
- **Strategy classifier**: exclude any repo README containing `polymarket`, `prediction market`, `claude-skills`, `obsidian`, `memory for AI` — these drift into strategy under the current heuristic but none carry a trading technique.
- **ml-ai classifier**: downweight Hermes-ecosystem repos (same competing-runtime bucket).

## Provenance

- Fetch script: `C:\Users\mattm\discord-export\fetch_readmes.py`
- Digest script: `C:\Users\mattm\discord-export\digest_trading_links.py`
- Per-module split: `C:\Users\mattm\discord-export\split_by_module.py`
- Scheduled refresh: Windows task `JarvisTrader_DiscordBookmarks_Refresh`, daily 06:15
- Synthesis agents: 6 parallel `general-purpose` agents, one per module, 2026-04-17 run
