# Health and safety API contract (Tier C)

**Purpose:** Stable keys for automation and dashboard **degraded** UX. Exact numeric values may change; **key names** should remain backward compatible unless versioned.

## `GET /health`

- **Auth:** Typically open or lightweight check — confirm with your deployment ([middleware/auth.py](../../engine/middleware/auth.py)).
- **Expect:** HTTP 200 when process is up; body often includes a `status` or service summary. Treat non-JSON or 503 as **engine down** for UI. The dashboard hook [dashboard/hooks/useEngineStatus.ts](../../dashboard/hooks/useEngineStatus.ts) polls `GET /health` every 10s and sets offline state on fetch failure (degraded UX without throwing).

**Stable keys** (match [dashboard/lib/api.ts](../../dashboard/lib/api.ts) `HealthResponse`):

| Key | Type | Meaning |
|-----|------|---------|
| `status` | string | `ok` \| `degraded` (e.g. DB check failed) |
| `version` | string | Engine API version string |
| `timestamp` | string | ISO-8601 UTC |
| `live_trading` | bool | Mirrors `LIVE_TRADING_ENABLED` |
| `kill_switch_active` | bool | From safety layer |
| `paper_mode` | bool | Inverse of live trading flag |
| `database` | string | `connected` \| `error` |
| `ibkr_connected` | bool | IB market data / gateway socket state |
| `schwab_connected` | bool | Schwab connector if configured |
| `uptime_seconds` | number | Process uptime |
| `llm_available` | bool | Present on engine responses; dashboard may ignore |

## `GET /health/full` (if mounted)

- Deeper dependency checks (DB, Redis, etc.). Use for **preflight**, not per-second polling.

## `GET /safety/status`

**Contract keys** (dashboard + scripts should tolerate optional fields but require core):

| Key | Type | Meaning |
|-----|------|--------|
| `kill_switch_active` | bool | Hard halt |
| `daily_pnl` | number | Context for limits |
| `daily_limit_breached` | bool | Circuit |
| `drawdown_breached` | bool | Circuit |

**Tests:** [engine/tests/test_api_contract_minimal.py](../../engine/tests/test_api_contract_minimal.py) — `test_safety_status_shape`, `test_health_contract_shape`

## `GET /safety/circuit-breakers`

**Contract keys:**

| Key | Type | Meaning |
|-----|------|--------|
| `all_clear` | bool | Aggregate OK |
| `kill_switch_active` | bool | Often mirrored here |
| `daily_limit_breached` | bool | |
| `drawdown_breached` | bool | |

**Tests:** `test_circuit_breakers_shape` in same file (requires `kill_switch_active`, `daily_limit_breached`, `drawdown_breached`).

## Changing this contract

1. Update **tests** in `test_api_contract_minimal.py` (or add new contract tests).
2. Update **dashboard** types / parsers in [dashboard/lib/api.ts](../../dashboard/lib/api.ts).
3. Note the change in session log or PR description.

## Metrics snapshot (repo hygiene)

Regenerate [docs/strategic/METRICS_SNAPSHOT.json](../strategic/METRICS_SNAPSHOT.json) after large router refactors:

```bash
python scripts/strategic_snapshot.py
```

CI runs this script in the **engine-test-fast** job to ensure it stays executable.
