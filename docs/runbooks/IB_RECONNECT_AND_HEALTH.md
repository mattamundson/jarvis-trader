# IB Gateway — reconnect behavior and health (Tier A)

## Auto-reconnect (engine)

[engine/execution/ib_gateway_connector.py](../../engine/execution/ib_gateway_connector.py) implements:

- `ConnectionState.RECONNECTING` and `_reconnect()` with exponential backoff (2s, 4s, 8s).
- `_max_reconnect_attempts` (default **3**) per disconnect cycle; heartbeat loop can reset attempts on a new disconnect.

**Limitation:** After max retries, connection stays failed until **process restart** or a future explicit `connect()` path. Treat **RISK-004** as “mitigated in code, not eliminated” — monitoring and alerts still required.

> **Scope note:** this covers reconnecting to a Gateway that is *still logged in*. It does
> **not** cover IBKR's daily forced logout of the Gateway process itself — nothing here can
> reconnect to a session that no longer exists. For that (the #1 cause of overnight blackouts)
> see [IB_GATEWAY_AUTO_LOGIN.md](IB_GATEWAY_AUTO_LOGIN.md).

## Operator actions

1. Confirm IB Gateway **paper** on port **4002** (see [CURRENT_STATE.md](../CURRENT_STATE.md)).
2. If engine shows disconnected after gateway bounce: **restart engine** ([restart_engine.ps1](../../restart_engine.ps1)) after confirming Gateway login.
3. Complete [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) once per environment change.

## Health endpoints

See [HEALTH_API_CONTRACT.md](HEALTH_API_CONTRACT.md) for JSON fields the dashboard and scripts should rely on.

## Data-freshness watchdog (`per_symbol_freshness`) — expected post-restart behavior

Distinct from the connector-level reconnect above: [engine/services/ib_data_watchdog.py](../../engine/services/ib_data_watchdog.py)
watches the **data leg** (not the socket) — it polls every `IBKR_DATA_WATCHDOG_INTERVAL`
seconds (default **30s**) and forces a reconnect if IBKR-sourced data has gone stale beyond
`IBKR_DATA_STALE_SECONDS` (default **180s**) during market hours.

`GET /health/full`'s `per_symbol_freshness` map (`{symbol: seconds_since_last_served}`) is
sourced from `DataManager._symbol_last_ts` — a **plain in-memory dict**, so it is always empty
immediately after a process restart and only gains an entry for a symbol once that symbol is
first served post-restart (`_mark_symbol_fresh()`, called on every non-empty `get_bars()`
result).

**Expected, not a symptom of an incident:** for the first few minutes after a restart it is
normal to see some symbols report elevated freshness (several hundred seconds) — that number
is counting from whenever the process booted (or from a value the watchdog is still catching
up to), not from a fresh serve, simply because the pipeline's per-symbol serve cadence hasn't
reached every watched symbol yet. This self-clears within roughly one watchdog poll cycle
(~30s) once serving resumes for that symbol — it is unrelated to the delayed-data /
live-market-data-subscription research from 2026-07-08 (that's about historical-bar *data type*
quality, not this serve-freshness bookkeeping). Only treat elevated `per_symbol_freshness` as a
real incident if it does **not** clear within roughly one watchdog interval, or if
`GET /health/full`'s `watchdog` sub-object shows the reconnect loop itself erroring.

## §4 — Operator verification drill (RISK-004)

Use a **paper** session only (Gateway **4002**). Goal: confirm engine observes disconnect and either reconnects within backoff or surfaces a failed health state deterministically.

1. Start IB Gateway (paper) and the engine; confirm `GET /health` shows `ibkr_connected: true` (or full health `ib_gateway` subsystem OK).
2. Note baseline: `GET /health/full` and optionally engine logs (`logs/jarvis.log`).
3. **Controlled disconnect:** log out or stop Gateway (or pull network) for 30–60 seconds.
4. **Observe:** engine logs should show reconnect attempts (`RECONNECTING`, backoff 2s / 4s / 8s). `GET /health` may show `ibkr_connected: false` during the window.
5. **Restore:** bring Gateway back; within one backoff cycle or manual `restart_engine.ps1`, confirm `ibkr_connected` returns true and market data resumes (see [MARKET_DATA_WATERFALL.md](MARKET_DATA_WATERFALL.md)).
6. **Record:** paste log excerpts + timestamps into `docs/session-logs/` (or PR) and add a one-line note to the RISK-004 changelog row when verified.

**Automated stub:** `engine/tests/test_ib_reconnect_contract.py` asserts the connector exposes `_reconnect` and a bounded retry constant (no live Gateway required).
