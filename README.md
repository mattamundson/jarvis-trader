# JARVIS Trader

AI-assisted trading stack: **Python/FastAPI engine** (multi-agent pipeline, risk gates, brokers) and **Next.js dashboard**. Intraday/daily backtests live under `engine/backtest/`.

## Requirements

- **Python 3.12** (recommended; avoid 3.14 for numpy/pandas-ta stacks)
- **Node.js** for the dashboard (npm or pnpm)

## Quick start — engine

From the repo root:

```bash
cd engine
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
```

Use the project venv (recommended) — `pip install` via `python -m pip` if `pip.exe` fails on your shell:

```bash
cd engine
.venv\Scripts\python -m pip install -r requirements-core.txt
```

Run the API (default port **8010**):

```bash
cd engine
.venv\Scripts\python -m uvicorn main:app --reload --host 0.0.0.0 --port 8010
```

- Health: `http://localhost:8010/health`
- Docs: `http://localhost:8010/docs`

Copy `engine/.env.example` to `engine/.env` and fill keys (never commit `.env`).

## Quick start — dashboard

```bash
cd dashboard
npm install
npm run dev
```

App: `http://localhost:3010`

## Backtest (example)

From `engine/`:

```bash
.venv\Scripts\python -m backtest.run_backtest --symbol SPY --start 2024-06-01 --end 2026-03-27 --interval 1h
```

JSON is written to `engine/backtest/results/` automatically. Summaries: `engine/backtest/results/SUMMARY.md`.

**2025 daily cache helpers** (Yahoo rate limits): `python -m backtest.build_daily_cache_2025` builds SPY daily from cached 1h and attempts ES=F for MES; if Yahoo blocks ES=F, the script falls back to an **SPY-return proxy** for ES levels (documented in `SUMMARY.md`).

## Local infrastructure (optional)

Postgres, Redis, QuestDB, Grafana:

```bash
cd infrastructure
docker compose up -d
```

Compose expects `infrastructure/postgres/init.sql` (included). Adjust ports if they clash with local services.

## Security

Do not commit OAuth client JSON, API keys, or `jarvis.env`-style secrets. Patterns for Google client JSON are in `.gitignore`.

## Project layout

| Path | Purpose |
|------|---------|
| `engine/` | FastAPI app, agents, execution, backtest |
| `dashboard/` | Next.js UI |
| `infrastructure/` | `docker-compose.yml` for data stores |
