# Paper ledger — writers and readers (B-first for the dashboard)

Companion to [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md). This doc names **who may write** vs **who reads** so validation metrics and the UI stay consistent.

## Mode B (engine API — dashboard default)

- **Writer:** `PortfolioTracker` persistence (SQLite / configured store) when legs are opened or closed via **`POST /portfolio/paper/trade`** and related portfolio routes.
- **Readers:** `GET /portfolio/paper/*`, `GET /portfolio/history/trades`, validation surfaces that query the same store.

Treat **B** as the **canonical book** for anything the Next.js dashboard shows through `fetchEngine`.

## Mode A (file-backed runner)

- **Writer:** `paper_runner` → `paper_positions.json`, `paper_trades_live.json` (and siblings under `engine/backtest/results/` per runner config).
- **Readers:** Headless jobs, ad-hoc scripts, or future dashboard features that explicitly read those files.

**A** is not merged into **B** unless **A→B sync** is enabled (`JARVIS_ENGINE_URL` + `JARVIS_API_KEY` on the runner host).

## `PaperTradeLogger` (`data/paper_trades.json`)

- **Always** appends fills to `data/paper_trades.json` (audit / IB connector paper simulation).
- When constructed with a **`PortfolioTracker`** and **`mirror_to_tracker=True`** (default), it also mirrors **full** net-position cycles per symbol: flat → non-zero → flat. **Partial** adds/reduces (net stays non-zero) are logged to JSON only until richer mapping exists.

`IBGatewayConnector` accepts optional **`portfolio_tracker`** and passes it through to `PaperTradeLogger` when you wire the engine book into the connector.

## Consolidation direction (engineering)

**B** remains canonical for the dashboard. JSON is a secondary audit; mirroring keeps connector fills aligned with **`PortfolioTracker`** for full round-trips. **A** (runner files) is unchanged — use **A→B sync** per [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md) when ops needs one view.
