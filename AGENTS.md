# AGENTS.md

Project memory and coding rules live in `CLAUDE.md` (root), `engine/CLAUDE.md`, and
`dashboard/CLAUDE.md` — read those first. This file adds environment notes for cloud agents.

## Cursor Cloud specific instructions

Two services make up the product: the **engine** (FastAPI, Python 3.12, port 8010) and the
**dashboard** (Next.js 15, port 3010). The dashboard proxies all engine calls through
`/api/engine/[...path]`, so it only needs the engine running on `localhost:8010`.

### Environment / dependencies

- The Python venv lives at `engine/.venv` (Linux path `engine/.venv/bin/...`, not the
  Windows `engine/.venv/Scripts/...` paths referenced throughout `CLAUDE.md`/docs).
- The startup update script provisions deps from `engine/requirements-core.txt` (NOT
  `engine/requirements.txt`). `requirements.txt` pins `questdb==1.2.1`, which has no
  Python 3.12 wheel and breaks the full install; `requirements-core.txt` is the
  CI-canonical set that resolves and includes the test deps (`hypothesis`, `respx`,
  `pypdf`). Heavy/optional libs (`ta-lib`, `vectorbt`, `nautilus_trader`, `langchain`,
  `openbb`) are intentionally excluded — engine modules guard those imports.
- `engine/.env` and `dashboard/.env.local` are gitignored and already created in the VM
  with a local dev `API_KEY` (the two values match so the dashboard can reach the engine).
  If `engine/.env` is missing, the engine exits at startup with "Missing Required
  Environment Variables". Recreate it with at least `API_KEY=<any value>` plus
  `MAX_DRAWDOWN_PCT=0.20` (the paper-phase override; `test_drawdown_recurrence_prevention`
  asserts the runtime value is `0.20`, while `config.py`'s code default is `0.10`).
- `ANTHROPIC_API_KEY` is unset, so the LLM agent pipeline (`/pipeline/run`) cannot produce
  decisions — every pipeline call fails the LLM provider chain. Everything else (safety
  layer, health, portfolio, backtest tooling, dashboard) works without it. Add the key to
  `engine/.env` to exercise the pipeline.

### Running the services

- Engine: from `engine/`, `.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8010`.
  Do NOT use `--reload` (duplicates IB connections). IB Gateway (port 4002) is not present,
  so repeated `ConnectionRefusedError` to `127.0.0.1:4002` in the log is expected and
  non-fatal — the data watchdog just retries.
- Dashboard: from `dashboard/`, `pnpm dev` (port 3010). Use `pnpm` only (npm is broken).
- Auth: all engine routes require header `X-API-Key: <API_KEY from engine/.env>`.

### Lint / test / build

- Engine lint: from `engine/`, `.venv/bin/ruff check . --config ruff.toml`.
- Engine tests: from `engine/`, `.venv/bin/python -m pytest tests/ -m "not slow"`
  (~2 min, 7000+ tests). `manual`/`integration_ib` tests auto-skip without IB Gateway.
- Dashboard typecheck: from `dashboard/`, `./node_modules/.bin/tsc --noEmit` (this is the
  type/lint gate — `pnpm lint` / `next lint` is unconfigured and prompts interactively).
- Dashboard build: from `dashboard/`, `pnpm run build`. Gotcha: running a production build
  while `pnpm dev` is live corrupts `.next` (dev then 500s with "Cannot find module
  './<chunk>.js'"). Stop the dev server first, build, then `rm -rf .next` and restart
  `pnpm dev` (or use `pnpm run build:clean`).
