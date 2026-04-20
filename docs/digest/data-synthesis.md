# Data Synthesis — from Discord digest

_Source: `C:\Users\mattm\discord-export\digest-raw\by-module\data.json` (6 items, 3 GitHub READMEs + 3 X posts). Evaluated 2026-04-16 against jarvis-trader data stack._

## TL;DR

Of 6 "data"-tagged items, **5 collapse into a single theme: the TradingView Desktop + CDP stack Matt already operates**. The 6th (`last30days-skill`) is a general-purpose research agent — fun, but orthogonal to futures data ingestion. **Net novel futures-data sources: zero.** The real signal from this batch is corroboration that `engine/data/tradingview_feed.py` + port-9222 CDP is the right architecture — two independent X threads and a third-party MCP repo all converged on the same pattern Matt shipped weeks ago.

## Already in jarvis-trader (dedup)

| Item | Already covered by | Notes |
|------|--------------------|-------|
| `tradingview/lightweight-charts` | `dashboard/` (Next.js 15.3) already has chart rendering; no blocker to swap if desired | Chart *rendering* library, not a data source. Would live in `dashboard/components/`, not `engine/data/`. |
| `tradesdontlie/tradingview-mcp` | `engine/data/tradingview_feed.py` + existing TradingView MCP on port 9222 | Same architecture (CDP debug port 9222), same 45+ indicator extraction pattern. Matt's version is already wired into the pipeline. |
| `milesdeutscher` X post ("Connect Claude to TradingView") | Same as above | Tutorial pointer, not a new source. |
| `mindsharexbt` X post (CCXT + Lightweight Charts) | CCXT is crypto-exchange only; lightweight-charts already handled | CCXT does NOT provide CME futures (MCL/MNQ/MES) — it's unified crypto-exchange wrapper. Skip. |
| `qkl2058` X post ("fredapi + Claude replaces Bloomberg") | `engine/data/fred_data.py` | Matt already has the FRED integration the tweet recommends. |

## Novel data sources — ranked

**None of the 6 items introduces a new futures-data source not already in the stack.** The one non-trivial candidate is research-adjacent, not data-ingestion:

### 1. `mvanhorn/last30days-skill` — multi-platform social research agent

- **Source**: https://github.com/mvanhorn/last30days-skill
- **Data it provides**: Reddit (upvotes + comments), X/Twitter, YouTube transcripts, TikTok, Polymarket odds, Hacker News, GitHub, Threads, Pinterest, Bluesky, Perplexity Sonar. Scored by engagement, synthesized by an agent judge.
- **Coverage**: **Social/news only — no market data, no futures, no tickers.** Polymarket is the closest thing to a "market" signal and it's event-based prediction markets, not commodities.
- **Free tier**: Reddit/HN/Polymarket/GitHub work zero-config. X needs browser session. YouTube needs `yt-dlp`. TikTok/IG/Threads/Pinterest gated by ScrapeCreators (10K free calls). Perplexity/Brave are pay-as-you-go.
- **Touch point**: NOT `engine/data/`. This overlaps with `engine/agents/social_analyst.py` (ApeWisdom + PRAW Reddit). Could augment social_analyst with a Polymarket-odds feature for event-risk detection (e.g., "OPEC meeting Dec 31 ceasefire odds"), but that's a **feature of social_analyst, not a new data module**.
- **Risk**: Heavy dependency tree, multiple paid/keyed APIs, output format is narrative prose (not structured). Would require a parser layer before any of it is usable as a signal feature.
- **Effort**: **Medium-to-large** to extract just the Polymarket-odds piece as a standalone signal; large if adopted whole.

**Verdict**: Install as a *skill for Matt* (personal research before/after sessions — "what's the community saying about crude oil supply disruption"), not as a pipeline data source. Polymarket odds specifically are the only piece with quant potential; defer until event-risk feature is prioritized.

## Noise / passed

- **`tradingview/lightweight-charts`** — Chart rendering library, not a data feed. Dashboard already has charts. Dedup.
- **`tradesdontlie/tradingview-mcp`** — Duplicate of existing TradingView feed architecture. Independent confirmation that the port-9222 CDP pattern is correct, but nothing to adopt.
- **`milesdeutscher` X post** — How-to content, no repo.
- **`mindsharexbt` X post** — Mentions CCXT (crypto-only, not futures) + lightweight-charts (dedup). **Polygon-style trap**: CCXT looks like a unified market-data API but covers no CME futures. Flag and pass.
- **`qkl2058` X post** — FRED advocacy; Matt already runs `fred_data.py`.

### Polygon-style trap flags

One corroborated warning: **CCXT** in the `mindsharexbt` tweet is the exact failure pattern as the 2026-04-16 Polygon incident — looks comprehensive, is crypto-only, no CME futures. If CCXT ever gets proposed for the stack, the answer is no.

## Raw grep receipts

```
engine/data/tradingview_feed.py                  ← existing (covers tradesdontlie/tradingview-mcp)
engine/data/fred_data.py                         ← existing (covers qkl2058 tweet)
engine/data/cot_fetcher.py                       ← existing
engine/data/sector_rotation.py                   ← existing
engine/data/polygon_*                            ← DISABLED for futures (2026-04-16)
engine/agents/social_analyst.py                  ← existing (nearest neighbor to last30days)
engine/indicators.py::compute_trin,classify_trin ← existing
dashboard/components/                            ← existing Next.js 15.3 charts
```

Discord-export inputs verified present:
```
C:\Users\mattm\discord-export\digest-raw\by-module\data.json                             (70 lines, 6 items)
C:\Users\mattm\discord-export\digest-raw\github\mvanhorn__last30days-skill.md            (~15KB truncated)
C:\Users\mattm\discord-export\digest-raw\github\tradingview__lightweight-charts.md       (141 lines)
C:\Users\mattm\discord-export\digest-raw\github\tradesdontlie__tradingview-mcp.md        (~15KB truncated)
```

## Recommendation

Close this module with **zero `engine/data/` additions**. Track one optional follow-up: if/when event-risk becomes a signal feature, evaluate adding a thin Polymarket client (via `last30days` or direct to `gamma-api.polymarket.com`) to `engine/agents/social_analyst.py`. Not a P0, not even a P2 — note it and move on.
