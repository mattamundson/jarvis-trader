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

<<<<<<< HEAD
=======
## Dashboard widget

`/health` mounts `IBGatewayStatus` (`dashboard/components/IBGatewayStatus.tsx`), which polls
`GET /ib/connection-test` and offers a **Connect** button when disconnected. That button only
calls `POST /data/reconnect` — the engine's existing idempotent data-leg reconnect (GT-38). It
cannot start the IB Gateway OS process itself (a FastAPI handler has no way to launch a desktop
app); Gateway startup/login stays a manual operator action per §Operator actions above. No
`/ib/connect` engine endpoint exists or is planned for this.

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
## Health endpoints

See [HEALTH_API_CONTRACT.md](HEALTH_API_CONTRACT.md) for JSON fields the dashboard and scripts should rely on.

## §4 — Operator verification drill (RISK-004)

Use a **paper** session only (Gateway **4002**). Goal: confirm engine observes disconnect and either reconnects within backoff or surfaces a failed health state deterministically.

1. Start IB Gateway (paper) and the engine; confirm `GET /health` shows `ibkr_connected: true` (or full health `ib_gateway` subsystem OK).
2. Note baseline: `GET /health/full` and optionally engine logs (`logs/jarvis.log`).
3. **Controlled disconnect:** log out or stop Gateway (or pull network) for 30–60 seconds.
4. **Observe:** engine logs should show reconnect attempts (`RECONNECTING`, backoff 2s / 4s / 8s). `GET /health` may show `ibkr_connected: false` during the window.
5. **Restore:** bring Gateway back; within one backoff cycle or manual `restart_engine.ps1`, confirm `ibkr_connected` returns true and market data resumes (see [MARKET_DATA_WATERFALL.md](MARKET_DATA_WATERFALL.md)).
6. **Record:** paste log excerpts + timestamps into `docs/session-logs/` (or PR) and add a one-line note to the RISK-004 changelog row when verified.

**Automated stub:** `engine/tests/test_ib_reconnect_contract.py` asserts the connector exposes `_reconnect` and a bounded retry constant (no live Gateway required).
