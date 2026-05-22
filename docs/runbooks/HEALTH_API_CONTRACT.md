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

## `paper_trades.idempotency_key` — NOT NULL since migration 032

Since migration 032 (applied 2026-05-21), `paper_trades.idempotency_key` is `TEXT NOT NULL`.

**Schema-level guarantee:** A caller that bypasses `insert_paper_trade()`'s runtime dedup check
can no longer store a NULL key that would defeat the UNIQUE INDEX
(`idx_pt_idempotency_key`, partial, `WHERE idempotency_key IS NOT NULL`).

**Key computation:** Every new row must carry a key computed by
`database._helpers.compute_order_idempotency_key(symbol, side, qty, price)`.
Formula: `SHA-256(symbol|side|qty_int|price_2dp|floor(epoch/5))[:32]`.

**Python-layer enforcement:** `insert_paper_trade()` now raises `TypeError` when
`idempotency_key` is empty or missing — fail-fast before any DB round-trip.

**Backfill note (existing rows):** The 16 rows that pre-dated migration 032 were backfilled
using the same SHA-256 formula but with the row's historical `entry_time` epoch as the bucket
source (not the current clock). This makes backfill keys:
- Deterministic (re-runnable migration produces the same keys)
- Historically grounded (bucket reflects actual trade entry time)
- Non-recomputable by future callers (the 5s bucket has long expired)

Rows where two historical entries fell in the same 5-second bucket received a `-<id>` suffix
on the later row's key (e.g. `bacca7b2a2056a50725b576d6f977f25-153`) to preserve UNIQUE
constraint compatibility. These suffixed keys are identifiable in forensic queries by the
presence of a hyphen after the 32-char hex prefix.

**Verify constraint is active:**
```bash
engine/.venv/Scripts/python -c "
import sqlite3
conn = sqlite3.connect('engine/data/jarvis_trader.db')
for row in conn.execute('PRAGMA table_info(paper_trades)'):
    if row[1] == 'idempotency_key':
        print('notnull:', row[3])  # must be 1
"
```

**Root cause closed:** 2026-05-09 6× phantom-trade incident (analysed 2026-05-11).
See `engine/tests/test_idempotency_constraint.py` for regression tests.

## Metrics snapshot (repo hygiene)

Regenerate [docs/strategic/METRICS_SNAPSHOT.json](../strategic/METRICS_SNAPSHOT.json) after large router refactors:

```bash
python scripts/strategic_snapshot.py
```

CI runs this script in the **engine-test-fast** job to ensure it stays executable.
