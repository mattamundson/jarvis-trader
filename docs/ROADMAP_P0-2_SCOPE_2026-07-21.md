# P0-2 — Route Execution Through the Real IB Gateway: Concrete Scope

**Status:** scoping (pre-implementation) · **Created:** 2026-07-21 · **Owner:** Amo · **Tag:** `[safety-review]` (Tier-3 sign-off required)
**Grounded in:** a 6-agent read-only survey of the execution subsystem (every claim below carries a `file:line`), the existing `docs/DESIGN_P0_order_path_binding.md`, and a live `/health` probe.

> **One-line summary:** The real `IBGatewayManager` is fully built and the production approval path already calls only methods it implements. P0-2 is **wiring + a feature flag + broker-observed proof**, not a bracket-engine build. The design doc's multi-day estimate was based on a `place_bracket_order` gap that does **not** sit on the live path.

---

## 1. The finding that sizes this whole task

The design doc (`DESIGN_P0_order_path_binding.md:108-135`) estimated "a focused multi-day task" because it believed `IBGatewayManager` lacked `place_bracket_order` (called at `safety_layer.py:1737`). That is true but **irrelevant to the production path**:

| Bracket mechanism | Method it calls | On the live approval path? | Supported by `IBGatewayManager`? |
|---|---|---|---|
| `submit_entry_with_stop` (entry + STP child + TP child, each a `place_paper_order` with `parent_order_id`) | `place_paper_order` ×3 | **YES** — `execute_approved_trade` uses it (`approval/service.py:264-290`) | **YES** — `ib_gateway.py:667`, sets `parentId` at `:746` |
| `submit_paper_bracket_order` | `place_bracket_order` | No (secondary) | No — method absent |
| `order_router.route_bracket_order` | `place_bracket_order` | No (order_router is not the approval path) | No — method absent |

**Verified:** `IBGatewayManager.place_paper_order(symbol, action, quantity, order_type, limit_price, aux_price, parent_order_id, order_ref)` at `ib_gateway.py:667-677`; `if parent_order_id is not None: ib_order.parentId = int(parent_order_id)` at `:745-746`, immediately before `self._ib.placeOrder(contract, ib_order)` at `:748`. The `test_ib_gateway_manager_parent_id.py` docstring claiming "no `parent_order_id` kwarg" is **stale** (describes a pre-fix state).

**Consequence:** the live path (`approve → execute_approved_trade → submit_entry_with_stop → place_paper_order ×3`) is a drop-in swap. The `place_bracket_order` gap only needs handling if we keep the secondary paths live (we will gate them off — see §5).

---

## 2. Current state (verified, with line refs)

**The two swap points** (`main.py`):
- `main.py:711` constructs `IBGatewayConnector(...)` — the in-process **simulator** (`ib_gateway_connector.py`, docstring: *"No actual orders sent to any broker"*; `connect()` at `:127-179` just sets `self._connected = True`, no socket).
- `main.py:476` `safety_layer.attach_ib_gateway(ib_paper_connector)` → sets `safety_layer._ib_gateway` (`safety_layer.py:281-283`); every order op reads that attribute.
- `main.py:477` `order_router.attach_ibkr(ib_paper_connector)` — second attach, same simulator instance.
- `main.py:717-721` `IBOrderManager(..., ib_gateway=ib_paper_connector, ...)` — bridge, also fed the simulator.
- `main.py:728-740` `PositionReconciler(ib_paper_connector, ...)` fire-and-forget on boot.

**The real manager** (`execution/ib_gateway.py`, `IBGatewayManager`, 1100 lines):
- `IBGatewayConfig` dataclass (`:215-244`): `host="127.0.0.1"`, `port=PAPER_TRADING_PORT` (4002), `client_id=1`, `timeout=10.0`, `readonly=False`, `account=""`. `__post_init__` **raises `ValueError` if port ∈ {4001, 7496}** (live ports permanently blocked).
- Real async `ib_async` client. `connect()` (`:346-357`) opens a real socket via `connectAsync` and confirms with `managedAccounts()`. `is_connected()` (`:414`) delegates to `self._ib.isConnected()`.
- Implements: `place_paper_order` (`:667`), `cancel_order` (`:774`), `get_open_orders` (`:807`), `get_order_status` (`:849`, includes `parent_order_id`), `get_positions` (`:913`), `get_account_summary` (`:868`), `get_executions` (`:958`), `get_portfolio_value` (`:950`), `health_check` (`:1012`).
- Contract build (`_resolve_contract`, `:433-480`): futures via `FUTURES_SYMBOL_MAP`; **quarterly roll** (`_nearest_quarterly_expiry`) for MES/MNQ/MGC/MYM/M2K, **monthly** (`_nearest_front_month`) for MCL.
- Currently instantiated **only** in tests + two smoke scripts (`smoke_ib_paper_order.py:111`, `hb1_paper_smoke.py:63`) — **never in `main.py`**.

**The data leg (already live on IB, must not collide):**
- `IBKRDataConnector` (`data/market_data.py`), constructed at `:952-959` with `client_id=resolve_data_client_id(self._config)`.
- `resolve_data_client_id` (`:184-199`): uses `IBKR_DATA_CLIENT_ID` if set, else **`IBKR_CLIENT_ID + 1`**. Live `.env` has `IBKR_CLIENT_ID=244`, so the **data leg runs at clientId 245**.
- Sets `reqMarketDataType(3)` = **DELAYED** (`:268-278`, override via `IB_MARKET_DATA_TYPE`).
- This is the `data_manager.ibkr` object `brokers_router.py:34` reads — a read-side data connection, **not** an order path.

**The P0-1 health probe (already done, verified real):**
- `_probe_execution_path(gateway)` at `routers/health_router.py:304-395`, called at `:717-719` against `safety_layer._ib_gateway` (the same object main.py attaches).
- `broker_ack` is a **real round-trip**: `await asyncio.wait_for(ib.reqAllOpenOrdersAsync(), timeout=4.0)` (`:368-379`); timeout/exception → `False`.
- `simulated` = "object holds no `_ib`/`ib` handle" (`:340-351`). `class_name` = `type(gateway).__name__`.
- Field is declared on `HealthResponse` (`api/models.py:211-225`) — not stripped. (`SubsystemStatus` separately uses `extra="allow"`.)
- **This is the falsifiable meter P0-2's proof reads.** Live now: `{"class_name":"IBGatewayConnector","simulated":true,"broker_ack":false}`.

---

## 3. The interface contract a real gateway must satisfy

Every call site on the attached gateway object (from grep across `engine/`, non-test):

| Method | Called by | `IBGatewayManager` has it? |
|---|---|---|
| `connect()` / `disconnect()` / `is_connected()` | `main.py`, order_router, reconciler | ✅ |
| `place_paper_order(..., parent_order_id=)` | `submit_entry_with_stop` (entry/STP/TP), `submit_paper_order`, reconciler emergency STP | ✅ (`:667`) |
| `get_order_status(id)` → dict incl. `parent_order_id` | `_verify_parent_linkage` (`safety_layer.py:1775`) | ✅ (`:849`) |
| `get_positions()` / `get_open_orders()` | reconciler, `IBOrderManager`, `flatten_all_positions` | ✅ |
| `cancel_order(id)` | rollback paths, `ActiveBracketRegistry` (duck-typed) | ✅ |
| `place_bracket_order(...)` | `submit_paper_bracket_order` (`safety_layer.py:1737`), `order_router.route_bracket_order` | ❌ **secondary paths only** |
| `modify_order(id, price)` | `order_router.route_modify` | ❌ |
| `get_quote(symbol)` | connector-internal fills (simulator only) | ❌ (real path uses live market data, no mock table) |
| `get_account_balance()` / `cancel_all_orders()` / `get_options_greeks()` / `attach_market_data()` / `set_on_disconnect_callback()` | connector-internal / order_router | ❌ / partial |

`_verify_parent_linkage` (`safety_layer.py:1765-1788`) is **class-agnostic** — its own comment says *"Works for both IBGatewayConnector (paper) and IBGatewayManager (live)."* No change needed there.

**Net:** the live approval path needs only the ✅ rows. The ❌ rows sit on secondary/dead paths that P0-2 will gate off (§5), deferring their real implementation to a follow-up.

---

## 4. Design decision (consistent with the existing design doc)

Adopt **Option C** from `DESIGN_P0_order_path_binding.md:59-78`: **feature-flagged dual binding.**

- **Default = simulator** (zero behavior change until deliberately flipped).
- New flag **`IB_PAPER_BROKER_ENABLED`** (does not exist yet; add to `config.py`). When `1`, `main.py` constructs and attaches the real `IBGatewayManager` instead of `IBGatewayConnector`.
- **ClientId: no new config needed.** Order leg connects with `IBKR_CLIENT_ID` (244); data leg is already at 245 (`IBKR_CLIENT_ID+1`). Verified distinct and tested (`tests/test_ib_data_client_id.py`). Assert-at-startup that order ≠ data clientId anyway (belt-and-suspenders).
- **Port:** `IBKR_PORT=4002` (paper). The `IBGatewayConfig` live-port guard blocks 4001/7496 at construction.
- **Account:** thread `IB_ACCOUNT_ID` (in `.env.example:31`, not yet a Settings field) into `IBGatewayConfig.account` so fills carry the right paper account.
- **Invariants unchanged:** `LIVE_TRADING_ENABLED=False`, `REQUIRE_HUMAN_APPROVAL=True`, kill switch stays hardcoded Python.

---

## 5. Exact changes (diff-level)

**5.1 `engine/config.py`** — add the flag + account field:
```python
IB_PAPER_BROKER_ENABLED: bool = Field(
    False,  # default OFF — flip only after the §6 broker-observed proof passes
    description="Attach the real IBGatewayManager (port 4002 paper) to the order path "
                "instead of the in-process IBGatewayConnector simulator.",
)
IB_ACCOUNT_ID: str = Field("", description="IB paper account id (e.g. DUxxxxxxx) for order routing")
```

**5.2 `engine/main.py`** — branch the construction (~`:711`) and attach (~`:476`):
```python
if settings.IB_PAPER_BROKER_ENABLED and settings.PAPER_TRADING:
    from execution.ib_gateway import IBGatewayManager, IBGatewayConfig
    order_gateway = IBGatewayManager(IBGatewayConfig(
        host=settings.IBKR_HOST, port=settings.IBKR_PORT,   # 4002; guard blocks 4001
        client_id=settings.IBKR_CLIENT_ID,                  # 244; data leg is 245
        account=settings.IB_ACCOUNT_ID,
    ))
    assert settings.IBKR_CLIENT_ID != resolve_data_client_id(settings), "order/data clientId collision"
    _connected = await order_gateway.connect()
    if not _connected:
        logger.critical("IB_PAPER_BROKER_ENABLED but gateway connect FAILED — refusing to fall back "
                        "to the simulator silently"); raise RuntimeError("real gateway connect failed")
else:
    order_gateway = ib_paper_connector  # existing simulator
# attach the chosen gateway everywhere the simulator is attached today:
safety_layer.attach_ib_gateway(order_gateway)   # main.py:476
order_router.attach_ibkr(order_gateway)          # main.py:477
```
(Feed `order_gateway` to `IBOrderManager` (`:717`) and `PositionReconciler` (`:733`) as well.)

**5.3 Gate off the unsupported secondary paths** so a missing method can never be hit on the real gateway:
- In `execute_approved_trade` the path is already `submit_entry_with_stop` (supported). Confirm `ENABLE_BROKER_BRACKETS=1` keeps it on that path, **not** `submit_paper_bracket_order`.
- Add a guard in `submit_paper_bracket_order` / `order_router.route_bracket_order`: if the attached gateway lacks `place_bracket_order`, raise a clear error rather than `AttributeError`. (Or implement `place_bracket_order` on `IBGatewayManager` as a thin wrapper over three `place_paper_order` calls — deferred to a follow-up unless a live caller is found.)
- **Action item:** confirm `order_router.route_order`/`route_bracket_order` is not on any live path (Agent survey suggests the approval path bypasses order_router; verify before flip).

**5.4 Disconnect / lifespan:** register `order_gateway.disconnect()` in the FastAPI lifespan shutdown; wire `set_on_disconnect_callback`-equivalent or a health-driven reconnect (`IBGatewayManager.reconnect()` exists at `:405`).

**5.5 Keep `ALLOW_MOCK_QUOTES=False`** (already default). The real gateway uses live market data, so the mock table never executes — but the flag staying False protects the fallback anyway.

---

## 6. The proof (broker-observed, not process-observed)

`pytest` green / `pm2 online` / `routed_to_ib:True` are **not** proof — all were true throughout the 3-month simulator incident. The proof is IB's own state:

1. **Probe flips.** With `IB_PAPER_BROKER_ENABLED=1` and IB Gateway up on 4002: `curl /health | jq .execution_path` → `{"class_name":"IBGatewayManager","simulated":false,"broker_ack":true}`. Then **kill IB Gateway**; within one poll `broker_ack` → `false`. (Proves a round-trip, not a config read.)
2. **Bracket rests at IB.** Submit **one 1-contract MES bracket** through the production approval path (`/pipeline/pending-approvals/{id}/approve`). From a **separate process on a fresh clientId**, `get_open_orders()` and assert the STP exists with `parent_id == entry_order_id` and `aux_price ==` the decision stop. Open IB Gateway's own order window → see three rows. (`hb1_paper_smoke.py` already does exactly this independent read-back — reuse it, but drive the entry through the *approval endpoint*, not a direct `submit_entry_with_stop` call.)
3. **Survives restart (the only real HB-1 proof).** `pm2 stop jarvis-engine`, wait 60s, re-query from the separate process: **the STP must still be resting at IB.** The simulator can never pass this — its "orders" die with the process.
4. **Cancel propagates.** Reject/cancel via the pipeline → confirm the order is gone at IB.
5. **Simulator path still green.** With the flag OFF, `test_safety_layer.py` + bracket-linkage tests stay green (no regression to the default path).

---

## 7. Risks & mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| **Instant-fill STP race** — IB paper sometimes fills the MKT entry before the STP child registers → momentary naked position | `IB_CONNECTOR_OVERVIEW.md:100-103` (documented, unresolved) | Use native OCA/`parentId` linkage; if it recurs, `ENABLE_BRACKET_ORDERS=0` workaround; **P0-3's continuous monitor is the real backstop** |
| **ClientId collision** evicts the data leg | two sockets on one clientId silently evict | Order=244, data=245 (already distinct); startup assert |
| **Delayed data** (`reqMarketDataType(3)`) | `market_data.py:268` | Acceptable for paper validation; flag as a known cap; real-time needs an IB market-data subscription (separate) |
| **Market-hours dependency** — proof steps need RTH for fills | — | Run the proof during RTH; the restart step works any time (resting order) |
| **Offline test blast radius** — `test_ib_gateway_offline_extended.py`, `test_ib_gateway_connector_offline.py`, mock-price tests pin *simulator* behavior | Agent survey §4 | These test the default (flag-off) path, which is unchanged; add a live-gated `integration_ib` suite for the real path (template exists: `test_ib_gateway_connector_safety_wiring.py` already builds `IBGatewayManager`) |
| **Silent fallback to simulator** on connect failure | — | `main.py` branch **raises** on connect failure when the flag is on (§5.2) — never degrade silently |
| **Secondary paths hit a missing method** (`place_bracket_order`, `modify_order`) | Agent survey §3 | Gate them off / raise clearly (§5.3); confirm they're not on a live path before flip |
| **`get_positions` marks fall back to $100** in the simulator's position path | `ib_gateway_connector.py:996-1011` | Real gateway returns IB marks; ensure the "refuse rather than fabricate" discipline extends to marks, not just fills |

---

## 8. Test plan

- **Unchanged (flag off):** all current offline suites keep passing — the default path is untouched.
- **Re-point / promote:** `test_ib_gateway_connector_safety_wiring.py` (already `IBGatewayManager`-based, live-gated) becomes the canonical real-path contract test; `test_ib_paper_e2e.py`, `test_order_ref_tagging.py` cover the vertical slice.
- **New:** an `integration_ib`-marked test that boots the engine with `IB_PAPER_BROKER_ENABLED=1`, submits a bracket via the approval endpoint, and asserts the resting STP at IB from a second clientId — codifying §6 step 2–3.
- **New unit:** `execute_approved_trade` routes to `submit_entry_with_stop` (not `submit_paper_bracket_order`) whenever `stop_price` is present and brackets enabled.
- **Guard test:** calling a secondary bracket path on a gateway lacking `place_bracket_order` raises a clear error, not `AttributeError`.

---

## 9. Sequencing

- **P0-1** (execution-path probe) — ✅ done and verified real (`health_router.py:304-395`).
- **P0-2** (this doc) — implement §5, prove §6, `[safety-review]` PR + Tier-3, then flip `IB_PAPER_BROKER_ENABLED=1` in `engine/.env`.
- **Unblocks P0-3** (continuous naked-position monitor): today `PositionReconciler` runs **once on boot against the simulator** (`main.py:728-740`) — it can only see the sim's own dict. After P0-2 it sees real IB positions/orders and becomes the foundation for the continuous `bracket_invariant_monitor` P0-3 describes.
- **Unblocks C1/C8/C10** on the readiness gate (`live_readiness.py`): C8 clears when `broker_ack:true`; C10 becomes checkable-real; C1's trades become real IB-paper fills that actually count toward the 30-trade threshold.

---

## 10. Rollback

Single lever: set `IB_PAPER_BROKER_ENABLED=0` in `engine/.env` and restart. `main.py` reverts to constructing/attaching `IBGatewayConnector`. No schema, no data migration, no code revert. The simulator path is never removed by P0-2 — only bypassed by a flag.

---

## 11. Open questions to resolve at implementation time

1. **Is `order_router` on any live path?** The approval path uses `safety_layer` directly; confirm `order_router.route_order`/`route_bracket_order` isn't invoked in production before relying on §5.3's gating. (`order_router.py:170-172` options branch passes a dict positionally as `symbol` — likely already-broken/dead; confirm.)
2. **Native `place_bracket_order` — implement or defer?** The live path doesn't need it. Decide whether to add a thin `IBGatewayManager.place_bracket_order` (3× `place_paper_order` + OCA group) now for completeness, or defer until a live caller exists.
3. **`IB_ACCOUNT_ID` value** for the running paper account (`DUxxxxxxx`) — confirm and set in `.env`.
4. **Reconnect policy** — health-driven `reconnect()` vs. disconnect-callback; pick one for the lifespan.
5. **`IBKR_PAPER_MODE=False` in live `.env`** while `PAPER_TRADING=True` — `IBKR_PAPER_MODE` has no observed call site, but reconcile the two before flip to avoid confusion.
