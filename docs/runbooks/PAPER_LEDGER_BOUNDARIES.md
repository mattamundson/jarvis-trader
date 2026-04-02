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

## Consolidation direction (engineering)

Longer term, collapse duplicate logging paths (`paper_trade_logger` vs `paper_tracker`) so one module owns durable paper state and others delegate. Until then, ops should assume **B** for dashboard truth and **A** for runner-only truth unless sync is on.
