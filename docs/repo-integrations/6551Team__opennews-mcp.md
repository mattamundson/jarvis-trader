---
repo: 6551Team/opennews-mcp
url: https://github.com/6551Team/opennews-mcp
stars: 1800
language: Python
license: MIT (client shim only; data backend is proprietary)
archived: false
pushed_at: unknown (active — recent commits on main)
analyzed_at: 2026-06-26
recommendation: defer
surfaces_with_value: [engine (schema idea only), docs]
---

# 6551Team/opennews-mcp

## Core value proposition
An MIT-licensed Python (FastMCP) server that aggregates 85+ real-time sources across six engine
categories — News (55 sources incl. Bloomberg/Reuters/CoinDesk), exchange Listings, OnChain
events, Meme-coin/Twitter sentiment, Market anomalies, and AI Prediction signals — and exposes
them to LLM assistants as MCP tools. Each article carries an AI impact score (0-100), a
directional signal (long/short/neutral), per-coin ratings, and bilingual summaries, with
WebSocket streaming. Critically, the server is a thin client: all data comes from the
proprietary gated backend `ai.6551.io` and requires an `OPENNEWS_TOKEN` — the MIT license
covers the client shim, not the data.

## How it maps onto jarvis-trader
jarvis-trader already has working, futures-oriented news ingestion, so this is a coverage
question, not a capability gap. `engine/agents/news_analyst.py` fetches Finnhub company-news +
Brave Search (`engine/data/brave_search.py`) + an optional data-manager feed, dedupes, and
LLM-synthesizes a structured `NewsReport` with `signal` (-1..+1), `confidence`, `event_type`,
and bull/bear catalysts — including an equity-proxy fallback (MCL→USO, MNQ→QQQ, MES→SPY,
MGC→GLD) precisely because our instruments are micro-futures. `engine/agents/fed_nlp.py` adds
macro/Fed language analysis. opennews-mcp's source mix is overwhelmingly crypto/meme-coin/
on-chain — categories with near-zero relevance to crude, Nasdaq, S&P, gold micros. The
overlapping TradFi sources (Bloomberg/Reuters) are already reachable via Finnhub/Brave, and
opennews gates them behind a paid third-party token pointed at a single vendor host.

## Surface analysis

### 1. Engine code
defer (schema idea only) — The only transferable idea is the article-level scoring schema: a
normalized 0-100 AI impact score plus a discrete directional label. `news_analyst.py` already
encodes an equivalent via continuous `signal`/`confidence`; adding a 0-100 impact field would
be additive polish, not new capability. Do NOT wire the runtime client — it hard-depends on
`ai.6551.io` + a proprietary token and delivers crypto-centric data our futures pipeline can't
use.

### 2. Project rules
no-fit — nothing here informs `.claude/rules/`. News/point-in-time discipline already lives in
`.claude/rules/testing.md` and `engine/backtest/news_blackout.py`.

### 3. Project skills
no-fit — no skill content. The `last30days` skill already covers multi-source sentiment sweeps.

### 4. Slash commands
no-fit — no command patterns to lift.

### 5. Subagents
no-fit — it's a data server, not an agent framework.

### 6. Docs
defer — the README's category taxonomy (News / Listing / OnChain / Meme / Market / Prediction)
and the "impact score + directional signal + per-entity rating" article model are a tidy
reference. At most a one-line pointer in `docs/data-source-audit-2026-04-16.md` noting opennews
as a crypto-news option if the mandate ever expands to crypto. Ideas only.

### 7. Dev tooling
no-fit — uses `uv`; we standardize on venv + pnpm. Our engine already hosts MCP servers
(`engine/tools/market_mcp_server.py`, `engine/discord/mcp_server.py`).

### 8. Dashboard
no-fit — no UI.

### 9. Ops / messaging
defer — the WebSocket-subscription + strategy-trigger streaming model resembles our push stack
(`engine/notifications/`, `engine/websocket/manager.py`), but we already stream signals and
route alerts. No integration; note only if we later want a live news-push channel.

## Integration plan
No integrations. Concretely:
1. Do not add opennews-mcp as an MCP server or dependency — its data host is proprietary/gated
   and crypto-oriented, off-mandate for our futures instruments.
2. Optional, low-priority: add an `impact_score` (0-100) field to `NewsReport` in
   `engine/agents/news_analyst.py` as a normalized companion to `signal` — our own additive
   change (not a code import), with its own test per `.claude/rules/testing.md`.
3. Add at most one reference line in `docs/data-source-audit-2026-04-16.md` flagging opennews as
   a crypto-news aggregator to revisit only if the mandate expands to crypto.

## License & attribution
MIT (permissive) — but the license covers only the client shim; the underlying `ai.6551.io`
service has separate, non-open terms. No code is being copied, so no attribution obligation is
triggered. If the optional `impact_score` idea is implemented, cite the source in the commit
body ("pattern inspired by 6551Team/opennews-mcp").

## Effort estimate
S — for the only defensible action (a reference doc line and/or an additive `impact_score` field
with a test). Full integration is not recommended at any size.

## Red flags
- Proprietary data behind an MIT client: looks open-source but is a thin wrapper over the gated
  `ai.6551.io` backend requiring a paid/registered token — no local capability, single-vendor
  lock-in.
- Domain mismatch: source mix is crypto / meme-coin / on-chain; we trade micro futures. Relevant
  TradFi sources are already covered by Finnhub + Brave.
- Duplication: overlaps `news_analyst.py`, `fed_nlp.py`, `brave_search.py`, and the `last30days`
  skill — adopting it would be net-negative surface area.
- A live external news-push feed would intersect point-in-time / news-blackout discipline
  (`.claude/rules/testing.md`, `engine/backtest/news_blackout.py`) — any streaming source must be
  publish-timestamp gated before it touches a decision.
