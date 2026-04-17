# himself65/finance-skills Integration Analysis

**Status**: TRADING-RELEVANT | MIT License | TypeScript Skills Pack  
**Last Updated**: 2026-04-17

## Overview

`himself65/finance-skills` is a 23-skill Claude Code plugin pack (1,171 stars, 125 forks, active as of 2026-04-16) covering financial analysis, social feeds, data providers, startup tools, UI widgets, and skill creation.

**License**: MIT — direct port permissible. Single-command install: `npx plugins add himself65/finance-skills`.

## Overlap vs. jarvis-trader `.claude/skills/`

| himself65 Skill | jarvis-trader Equivalent | Gap |
|---|---|---|
| earnings-preview, earnings-recap, estimate-analysis | None | Stock options + fundamental analysis |
| etf-premium, saas-valuation-compression | None | Equity derivatives, valuation patterns |
| sepa-strategy | Hidden Pivots (wired in pipeline.py) | SEPA pattern detection (Minervini TT) |
| options-payoff | None | Options Greeks + payoff visualization |
| yfinance-data | COT fetcher + sector_rotation | Broader equity data (financials, dividends) |
| discord-reader, telegram-reader, twitter-reader, yc-reader | openclaw agent + Corey alerts | Read-only social feeds (no write) |
| finance-sentiment | SocialAnalyst (ApeWisdom) | Multi-source sentiment (X, Reddit, news, Polymarket) |
| funda-data | None | Real-time quotes + 60+ endpoints |
| hormuz-strait | None | Geopolitical risk (oil supply) |
| startup-analysis | None | VC/founder/applicant frameworks |
| generative-ui | jarvis-canvas | Widget rendering (Gamma vs. HTML/SVG) |
| skill-creator | agent-debate-explain | Skill evaluation + iteration framework |

## Trade-Relevant Surfaces

### High-Value (Direct Integration)
- **sepa-strategy**: Minervini trend template pattern detection — complement Hidden Pivots regime detection
- **finance-sentiment**: Multi-source sentiment (X, Reddit, news, Polymarket) vs. current ApeWisdom-only model
- **funda-data**: 60+ endpoint API (real-time quotes, options flow, SEC filings) — fills fundamental data gap
- **options-payoff**: Dynamic Greeks + payoff charts for MCL/MNQ options trading ideas

### Moderate (Exploratory)
- **yfinance-data**: Broader equity data (earnings, dividends, splits) — complement COT research
- **etf-premium**: ETF arbitrage / sector hedge pair-trading (MCL/MNQ correlations)
- **discord-reader, twitter-reader**: Read-only feeds — dedup with Corey+openclaw agent

### Low (Outside Scope)
- **earnings-preview/recap, estimate-analysis**: Stock-only (jarvis-trader = futures)
- **hormuz-strait, startup-analysis**: Geopolitical/VC analysis (not trading signal)
- **skill-creator**: Duplicate of agent-debate-explain framework
- **generative-ui**: Overlap with jarvis-canvas; HTML/SVG widgets less portable than Gamma

## Recommendation

**RECOMMENDATION**: Selective port — sepa-strategy, finance-sentiment, funda-data, options-payoff as standalone skill modules.

**SURFACES**: Minervini pattern detection (regime filter), multi-source sentiment aggregator (debate signal), real-time fundamental data API, options visualization widget.

**EFFORT**: ~20 hrs (sepa-strategy logic ported to Python + integrated into pipeline.py:838-862; sentiment aggregator wired into social_analyst.py; funda-data endpoint wrapped as local FastAPI route; options UI ported to jarvis-canvas).

**License**: MIT — no compliance barriers.

**Decision Gate**: Defer full port until post-paper-trading. Sepa-strategy alone is immediate value (2–3 hrs integration into regime filter at `engine/agents/debate.py:45-54`).
