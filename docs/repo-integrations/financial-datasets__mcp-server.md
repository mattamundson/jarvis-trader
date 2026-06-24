---
repo: financial-datasets/mcp-server
url: https://github.com/financial-datasets/mcp-server
stars: 2200
language: Python
license: MIT
archived: false
pushed_at: 2026-06 (active, exact date not captured)
analyzed_at: 2026-06-24
recommendation: noise
surfaces_with_value: []
---

# financial-datasets/mcp-server

## Core value proposition
A Model Context Protocol server that exposes the Financial Datasets API as 10 MCP
tools so an LLM assistant can pull company fundamentals, stock/crypto prices, and
company news without writing API calls. It is a thin, well-made data wrapper — the
value is the data, not any analytics.

## Surface analysis

### 1. Engine code
`no-fit` — The server's headline tools are equity **fundamentals**
(`get_income_statements`, `get_balance_sheets`, `get_cash_flow_statements`). The
trading mandate is micro **futures** (MCL crude, MNQ/MES indices, MGC gold) plus
options. A futures contract has no income statement, so these tools are structurally
inapplicable. `engine/agents/fundamental_analyst.py` already encodes this: for
futures it uses **FRED macro** (Fed funds, 10Y, VIX, yield curve), reaching for
company financials only on equity symbols the system does not trade.

### 2. Project rules
`no-fit`

### 3. Project skills
`no-fit`

### 4. Slash commands
`no-fit`

### 5. Subagents
`no-fit`

### 6. Docs
`no-fit`

### 7. Dev tooling
`no-fit`

### 8. Dashboard
`no-fit`

### 9. Ops / messaging
`dedup-data` — Price and news tools duplicate existing wiring:
`get_current_stock_price` / `get_historical_stock_prices` are covered by Polygon
(`engine/data/polygon_stream.py`), IBKR, yfinance, and TradingView
(`engine/data/tradingview_feed.py`); `get_company_news` is covered by
`engine/agents/news_analyst.py`, `engine/data/brave_search.py`, and NewsAPI. Crypto
tools (`get_crypto_prices`, etc.) are out of mandate.

## Integration plan
No integrations; recommend classify as noise. Every tool is either out-of-mandate
(fundamentals, crypto) or duplicates an existing data source (prices, news).

## License & attribution
MIT — clean, but nothing to attribute since nothing is integrated.

## Effort estimate
S (to NOT integrate). Any forced integration would be M and net-negative.

## Red flags
- Mandate mismatch: equity/crypto fundamentals on a futures+options account.
- Adds a paid third-party API dependency (Financial Datasets API key) for data the
  system already sources elsewhere.
- Re-opening the "do we trade equities?" question contradicts the canon
  (futures + options only, $10K, MCL + MNQ).

## Reconsider-if
Only revisit if the mandate ever expands to single-name equities or crypto. Until
then this is a clean skip.
