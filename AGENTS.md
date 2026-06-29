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

### LLM provider — local Ollama option (no cloud key)

The engine's `JarvisLLMClient` (`engine/llm/client.py`) defaults to `JARVIS_LLM_PROVIDER=ollama`
and needs NO `ANTHROPIC_API_KEY` in that mode — it routes agent calls to a local Ollama
runtime (`OLLAMA_HOST`, `OLLAMA_MODEL`). To validate the agent/LLM path without cloud keys:

- Run `ollama serve` (installed at `/usr/local/bin/ollama`); pull a small model
  (`ollama pull llama3.2:1b`).
- In `engine/.env` set `JARVIS_LLM_PROVIDER=ollama`, `OLLAMA_HOST=http://127.0.0.1:11434`,
  `OLLAMA_MODEL=llama3.2:1b`, then restart the engine. `/health` then reports
  `primary_provider: ollama` and a served call flips `active_provider` to `ollama`.
- **CPU/Firecracker gotcha:** the VM advertises AVX-512 but Ollama's auto-selected AVX-512
  CPU runner **segfaults on warmup** here. The AVX-512 `libggml-cpu-*` variants were moved to
  `/usr/local/lib/ollama/_disabled_avx512/` so it falls back to the stable AVX2 (`haswell`)
  backend. If Ollama is reinstalled/upgraded, re-hide those variants.
- CPU inference of even a 1B model is slow (~30–70s/call); a full 10-agent pipeline run is
  impractical on CPU. For real Claude behavior set `ANTHROPIC_API_KEY` instead (and remove the
  `JARVIS_LLM_PROVIDER=ollama` line so the Anthropic path is used).
- Note: a full `/pipeline/run` also needs market-data bars (IB Gateway or `POLYGON_API_KEY`);
  without them the pipeline short-circuits before the LLM stages regardless of provider.

#### Vertex AI (Claude on Google Cloud) — preferred non-Anthropic-key path

Runs the same Claude models via GCP (no Anthropic API key), using `AsyncAnthropicVertex`
+ google-auth ADC (`engine/llm/client.py:_build_vertex_client`). Both deps are installed.
To activate (a ready, commented block is in `engine/.env`):
1. Comment out `JARVIS_LLM_PROVIDER=ollama` (`use_vertex` requires provider != "ollama").
2. Set `JARVIS_CLAUDE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_PROJECT_ID`, `ANTHROPIC_VERTEX_REGION`
   (e.g. `us-east5`).
3. Provide GCP ADC: either `GOOGLE_APPLICATION_CREDENTIALS=<service-account.json path>` or
   `gcloud auth application-default login`. The service account needs the **Vertex AI User**
   role, and **Claude models must be enabled in Vertex Model Garden** for that project/region.
4. Restart; `/health` should report `primary_provider: vertex`. Keep Ollama as a local
   fallback until Vertex is confirmed (don't remove it before ADC works, or the LLM path
   breaks with no provider).

### External service: master-api (:8030)

The dashboard talks to a SEPARATE `master-api` service at `NEXT_PUBLIC_MASTER_API_URL`
(default `http://127.0.0.1:8030`) via `dashboard/lib/masterApi.ts`. This service is NOT in
this repo and is not started by the engine/dashboard. When it is absent (the default in
this environment):

- `/master`, `/master/finances`, `/master/trading` show "Master API unreachable on :8030"
  banners (expected).
- The "honest deduped trade record" (`useHonestTrades` → `/master/trading/realized`) is
  unavailable, so widgets on `/stats`, `/journal`, `/performance`, and `/backtest` render
  "Failed to fetch"/"unavailable" states. These are NOT engine bugs — they need master-api.

`/strategy-c` showing `Engine error 404: /v1/strategy_c/signal` is also expected when no
live Strategy-C signal has been generated; the page prints the command to create one.

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
