# A-01 runtime observation receipt — 2026-09-12

**Capture mode:** read-only loopback GETs + OS port listing  
**Capital authority:** paper only  
**Broker mutation:** none  
**Credential access:** none  
**Evidence rung:** E2 for the specific runtime-read fields below only

## Observed endpoints

| Endpoint | Result |
|---|---|
| `http://127.0.0.1:8010/health` | JSON returned |
| `http://127.0.0.1:8010/openapi.json` | OpenAPI JSON returned; 409 paths |
| `http://127.0.0.1:3010/` | `401 Unauthorized`; Basic auth realm present; no credentials used |

## Redacted health facts

| Field | Observed value |
|---|---:|
| `status` | `ok` |
| `version` | `1.1.0` |
| `live_trading` | `false` |
| `kill_switch_active` | `true` |
| `paper_mode` | `true` |
| `database` | `connected` |
| `ibkr_connected` | `true` |
| `ibkr_execution_connected` | `true` |
| `execution_connected_verified` | `false` |
| `ib_execution_stale` | `true` |
| `ibkr_data_connected` | `false` |
| `ibgateway_alive` | `false` |
| `ibgateway_port` | `4002` |
| `ibkr_broker_probe_ok` | `true` |
| `market_data_fresh` | `true` |

## Port observations

| Port | Observation |
|---:|---|
| 3010 | LISTENING, dashboard PID observed as `43660` |
| 8010 | LISTENING, engine PID observed as `47136` |
| 4002 | not observed as local LISTENING in the netstat excerpt |

## Blocking dispositions

- `execution_connected_verified=false` and `ib_execution_stale=true` prevent treating the broker execution spine as verified.
- `ibgateway_alive=false` while `ibkr_broker_probe_ok=true` requires explicit broker-spine disposition before ISG-0 closure.
- Loaded risk-policy values and broker account identity remain unsigned/unobserved in this receipt.
- This receipt does **not** authorize runtime trading changes, risk changes, canary credentials, or live trading.
