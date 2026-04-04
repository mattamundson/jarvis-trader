# Dev API key rotation (engine + dashboard)

The engine expects `X-API-Key` on protected routes. The Next.js dashboard sends the same value from `NEXT_PUBLIC_ENGINE_API_KEY`. **Both must match.**

## One-command rotation (recommended)

From the **repository root**:

```bash
python scripts/rotate_dev_api_key.py
```

This will:

1. Create `engine/.env` from `engine/.env.example` if it does not exist.
2. Set `API_KEY` in `engine/.env` to a new random value.
3. Set `NEXT_PUBLIC_ENGINE_API_KEY` in `dashboard/.env.local` to the **same** value (creating the file with a short header if needed).

Then restart:

- Engine: `.\restart_engine.ps1` (or your usual uvicorn command — **no `--reload`**).
- Dashboard: `cd dashboard && pnpm dev`.

## Manual rotation

1. Copy `engine/.env.example` → `engine/.env` if you have no `.env` yet.
2. Pick a long random secret (e.g. `openssl rand -hex 32` on macOS/Linux, or Python `secrets.token_urlsafe(32)`).
3. Set `API_KEY=<secret>` in `engine/.env`.
4. Set `NEXT_PUBLIC_ENGINE_API_KEY=<same secret>` in `dashboard/.env.local`.

## Verify

```bash
# Replace with the API_KEY value from engine/.env
curl -s http://localhost:8010/safety/status -H "X-API-Key: YOUR_KEY_HERE"
```

Expect JSON with `kill_switch_active` (no `401`).

## Do not commit

- `engine/.env`
- `dashboard/.env.local`

`engine/.env.example` stays in git with **placeholders only**.
