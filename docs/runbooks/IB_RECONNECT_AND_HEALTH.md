# IB Gateway — reconnect behavior and health (Tier A)

## Auto-reconnect (engine)

[engine/execution/ib_gateway_connector.py](../../engine/execution/ib_gateway_connector.py) implements:

- `ConnectionState.RECONNECTING` and `_reconnect()` with exponential backoff (2s, 4s, 8s).
- `_max_reconnect_attempts` (default **3**) per disconnect cycle; heartbeat loop can reset attempts on a new disconnect.

**Limitation:** After max retries, connection stays failed until **process restart** or a future explicit `connect()` path. Treat **RISK-004** as “mitigated in code, not eliminated” — monitoring and alerts still required.

## Operator actions

1. Confirm IB Gateway **paper** on port **4002** (see [CURRENT_STATE.md](../CURRENT_STATE.md)).
2. If engine shows disconnected after gateway bounce: **restart engine** ([restart_engine.ps1](../../restart_engine.ps1)) after confirming Gateway login.
3. Complete [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) once per environment change.

## Health endpoints

See [HEALTH_API_CONTRACT.md](HEALTH_API_CONTRACT.md) for JSON fields the dashboard and scripts should rely on.
