# Awesome Quant tool-intake evidence gate

Status: research/control artifact only. This wave does not vendor, install, or
make any quant library an operational dependency. No live trading config, paper
trading config, risk limits, kill-switch state, broker routing, API keys, `.env`
files, PM2, active instrument gates, scheduled tasks, or order behavior are
changed.

## Source mined

- Reference repo: `mattamundson/awesome-quant`
- Reference commit: `b7919e9`
- Source role: curated catalog of quantitative finance libraries, data sources,
  backtesting frameworks, analytics packages, books, and commercial services.
- Selected files reviewed locally:
  - `README.md`
  - `site/projects.csv`
  - `AGENTS.md`
  - `quants.md`

## Coverage proof

Prior waves mined specific tools and domains: FRED/ALFRED, Lightweight Charts,
TradingView MCP, prediction-market backtesting, Polymarket risk controls,
ATLAS/GIC autoresearch, `claude-trading-skills`, and `amo-arbitrage`.
`awesome-quant` adds a different non-duplicative control: **a vendor/tool catalog
is not a strategy backlog; every candidate dependency needs an intake scorecard
before it can enter JARVIS architecture.**

This bridge encodes one plain rule: a vendor/tool catalog is not a strategy backlog.
The source catalog contains 498 parsed entries. The highest-density areas
are trading/backtesting, market data, pricing, risk/portfolio, and technical
indicators. That is useful for discovery, but dangerous if treated as endorsement.
JARVIS should mine it as a short-list source only, then require evidence gates
for maintenance, licensing, data provenance, dependency risk, execution-surface
risk, and overlap with existing JARVIS functionality.

## Parsed category snapshot

| Category | Entries |
|---|---:|
| Trading & Backtesting | 105 |
| Market Data & Data Sources | 88 |
| Financial Instruments & Pricing | 71 |
| Reproducing Works, Training & Books | 52 |
| Portfolio Optimization & Risk Analysis | 36 |
| Technical Indicators | 24 |
| Time Series Analysis | 24 |
| Numerical Libraries & Data Structures | 23 |
| Commercial & Proprietary Services | 22 |
| Cross-Language Frameworks | 15 |
| Visualization | 8 |
| Excel & Spreadsheet Integration | 8 |
| Factor Analysis | 7 |
| Prediction Markets | 5 |
| Calendars & Market Hours | 5 |
| Sentiment Analysis & Alternative Data | 2 |
| Related Lists | 2 |
| Quant Research Environments | 1 |


Relevant trading-system entries across the main implementation categories: **343**.

## High-visibility examples that still require intake review

| Project | Category | Repo | Stars | Last commit |
|---|---|---|---:|---|
| OpenBB Terminal | Market Data & Data Sources | `OpenBB-finance/OpenBBTerminal` | 63674 | 2026-03-24 |
| freqtrade | Trading & Backtesting | `freqtrade/freqtrade` | 48113 | 2026-03-28 |
| ccxt | Trading & Backtesting | `ccxt/ccxt` | 41552 | 2026-03-28 |
| Qlib | Trading & Backtesting | `microsoft/qlib` | 39430 | 2026-03-10 |
| vnpy | Trading & Backtesting | `vnpy/vnpy` | 38498 | 2026-01-14 |
| yfinance | Market Data & Data Sources | `ranaroussi/yfinance` | 22379 | 2026-03-19 |
| nautilus_trader | Trading & Backtesting | `nautechsystems/nautilus_trader` | 21469 | 2026-03-28 |
| backtrader | Trading & Backtesting | `backtrader/backtrader` | 20948 | 2023-04-19 |
| zipline | Trading & Backtesting | `quantopian/zipline` | 19556 | 2020-10-14 |
| Lean | Trading & Backtesting | `QuantConnect/Lean` | 18123 | 2026-03-25 |
| QuantConnect | Trading & Backtesting | `QuantConnect/Lean` | 18123 | 2026-03-25 |
| akshare | Market Data & Data Sources | `jindaxiang/akshare` | 17802 | 2026-03-27 |


These examples are not recommendations to adopt them. They are examples of the
kind of tool candidates that need formal intake before being mentioned in a
JARVIS implementation plan.

## JARVIS quant-tool intake classes

| Class | Examples | Required gate |
|---|---|---|
| `core_numeric` | NumPy, SciPy, pandas, Polars | Already used or benchmarked against current stack; no duplicate abstraction |
| `market_data_source` | OpenBB, yfinance, exchange/venue APIs | Source terms, freshness SLA, outage behavior, raw artifact hashes |
| `backtest_engine` | Lean, NautilusTrader, Backtrader, Qlib | Deterministic replay parity, cost/slippage model, no live broker calls in tests |
| `pricing_risk_library` | QuantLib, py_vollib, FinancePy, rateslib | Unit parity to known formulas/fixtures and model-boundary docs |
| `technical_indicator_library` | TA-Lib, pandas-ta, ta | Indicator definition parity and warmup/null behavior fixtures |
| `portfolio_risk_tool` | PyPortfolioOpt, Riskfolio-Lib, empyrical | Constraint transparency, covariance/stability diagnostics, outlier handling |
| `visualization_dashboard` | Lightweight Charts, Plotly, Bokeh | Read-only rendering, source provenance, no trade action coupling |
| `commercial_service` | paid feeds/platforms | Pricing/terms, export rights, uptime/SLA, key hygiene, replacement plan |
| `reference_only` | books/lists/tutorials/stale repos | Notes only; cannot become dependency or promotion evidence |

## Required intake scorecard before adoption

A future JARVIS tool/dependency proposal must include:

1. Source repo/service URL and reviewed commit/version.
2. Intended JARVIS role and intake class.
3. License/commercial terms and key/provider requirements.
4. Maintenance signal: last release/commit, issue health, test/CI status, and
   dependency footprint.
5. Overlap check against current JARVIS code and prior Waves 1-31.
6. Data/provenance contract if it provides market data or derived indicators.
7. Deterministic fixture proving output shape and edge-case behavior.
8. Explicit blocked influence on trading runtime, broker routing, risk limits,
   kill switches, `.env`, PM2, and active instrument gates.
9. Rollback/replacement plan if the tool becomes unavailable or stale.
10. Human approval if the proposal adds a runtime dependency or paid service.

## Allowed next steps

- Use `awesome-quant` as a discovery index for future explicit tool-evaluation
  tickets.
- Add offline fixture validators for specific tool candidates when a concrete
  implementation need exists.
- Keep rejected/stale/duplicative candidates visible in decision logs to prevent
  repeated rediscovery.

## Blocked without a separate `[safety-review]` PR

- Installing or vendoring a library from the catalog into JARVIS runtime.
- Adding provider/API keys, commercial accounts, or `.env` changes.
- Wiring catalog entries into live/paper execution, risk, broker routing, PM2, or
  scheduled tasks.
- Treating stars, catalog inclusion, or marketing claims as proof of strategy edge.
