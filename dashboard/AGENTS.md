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
- Deps come from `engine/requirements-core.txt` (not `engine/requirements.txt`) plus
  the CI ruff pin `ruff==0.8.0`. Dashboard install is pnpm `10.33.2` with
  `pnpm install --frozen-lockfile`. See the root `AGENTS.md` for why.
- `engine/.env` and `dashboard/.env.local` are gitignored. A missing `engine/.env` is
  created with only `API_KEY=jarvis-dev-key-change-me`, and `dashboard/.env.local` gets
  the matching `ENGINE_API_KEY`. Never overwrite an existing `engine/.env`, and do not
  add safety overrides to the placeholder (pytest reads that file).
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
- Engine tests: from `engine/`, `env -u PYTHONPATH .venv/bin/python -m pytest tests/`.
  Do not pass `-m`. A CLI `-m` replaces the `pyproject.toml` exclusion of `manual` and
  `integration_ib`, and those tests submit real paper orders when IB Gateway is up.
  See the root `AGENTS.md`.
- Dashboard typecheck: from `dashboard/`, `./node_modules/.bin/tsc --noEmit` (this is the
  type/lint gate — `pnpm lint` / `next lint` is unconfigured and prompts interactively).
- Dashboard build: from `dashboard/`, `pnpm run build`. Gotcha: running a production build
  while `pnpm dev` is live corrupts `.next` (dev then 500s with "Cannot find module
  './<chunk>.js'"). Stop the dev server first, build, then `rm -rf .next` and restart
  `pnpm dev` (or use `pnpm run build:clean`).
