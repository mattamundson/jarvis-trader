# Paper data — source of truth (P0.4–P0.6)

**Ledger boundaries (who writes B vs A):** [PAPER_LEDGER_BOUNDARIES.md](PAPER_LEDGER_BOUNDARIES.md)

**Decision (default ops): A+B with optional sync**

| Mode | Source | Use when |
|------|--------|----------|
| **A** | `paper_runner` → `engine/backtest/results/paper_positions.json`, `paper_trades_live.json` | Headless hourly loop without depending on FastAPI uptime. |
| **B** | Engine `PortfolioTracker` + SQLite → `/portfolio/paper/*`, `/portfolio/history/trades` | Dashboard, API consumers, command center. |
| **A→B sync** | Set `JARVIS_ENGINE_URL` + `JARVIS_API_KEY` on the runner host; runner POSTs opens/closes to `/portfolio/paper/trade`. | When ops wants a **single** dashboard view aligned with the runner. |

## Partial exits

Runner sync uses **full close** semantics in the engine (`close_trade` is per leg). Partial scale-outs in the runner may not close the engine leg until the strategy fully exits — see [`engine/backtest/paper_runner.py`](../../engine/backtest/paper_runner.py) comments.

## Dashboard alignment

Pages under [`dashboard/app/paper/`](../../dashboard/app/paper/) and portfolio widgets use `fetchEngine` / `postEngine` from [`dashboard/lib/api.ts`](../../dashboard/lib/api.ts) → Next rewrite `/api/engine/*` → engine. They are **B-first** (engine APIs). File-backed **A** data is not read directly by the dashboard unless explicitly added later.

## PM2 / scheduler (runner sync)

On the host that runs `paper_runner` with **A→B sync**, set:

| Variable | Example | Must match |
|----------|---------|------------|
| `JARVIS_ENGINE_URL` | `http://127.0.0.1:8010` | Engine base URL (no trailing slash) |
| `JARVIS_API_KEY` | (secret) | Engine `API_KEY` in `engine/.env` |

**PM2** (illustrative): `pm2 start ...` or ecosystem file with the above in `env`. **Windows Task Scheduler**: same vars on the task’s environment block.

After a deliberate open + full close, confirm `GET /portfolio/history/trades` (via dashboard or `fetchEngine`) shows the leg; positions should be empty after close. Partial exits may lag until full strategy exit (see `paper_runner` comments).

## Dashboard path audit (paper + command center)

- [`dashboard/app/paper/page.tsx`](../../dashboard/app/paper/page.tsx) and [`dashboard/app/command-center/page.tsx`](../../dashboard/app/command-center/page.tsx) use `fetchEngine` / `postEngine` for engine-backed data.
- Many **shared widgets** still call `fetch("/portfolio/...")` relative to the Next origin; those only reach the engine if you add a matching rewrite or migrate them to `fetchEngine` (`/api/engine/...`). Prefer `fetchEngine` for new work.

## Verification

1. Run [`engine/scripts/verify_p0_paper_ib.py`](../../engine/scripts/verify_p0_paper_ib.py) with engine up + API key.
2. Complete sign-off table in [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md).
