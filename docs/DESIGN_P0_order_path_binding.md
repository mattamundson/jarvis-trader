# P0 — Order-Path Binding: Design Options

_Decision doc for the Phase-0 prerequisite. 2026-07-21. Complements
`ROADMAP_TO_AUTONOMOUS_2026-07-21.md` P0-1..P0-4 (this frames the **decision**;
the roadmap lists the tasks). Written from a verified read of the binding sites;
items marked ⚠️ still need a code read before implementation._

## The problem (verified)

The live pipeline binds the **simulator** to the safety layer, not a broker:

- `main.py:46` imports `IBGatewayConnector` (the pure-Python in-process sim).
- `main.py:711` constructs `ib_paper_connector = IBGatewayConnector(...)`.
- `main.py:476` calls `safety_layer.attach_ib_gateway(ib_paper_connector)`.
- `risk/safety_layer.py:281` `attach_ib_gateway()` sets `self._ib_gateway`, and
  every order op (`place_paper_order`, `place_bracket_order`, `get_order_status`,
  `is_connected`, `get_positions`, `cancel_order`) calls through that attribute.
- The **real** `IBGatewayManager` (`execution/ib_gateway.py`) is imported only as
  a type hint at `safety_layer.py:32` (falls back to `None` on ImportError) and
  is **instantiated nowhere**.

Consequence: `place_bracket_order` / `place_paper_order` write into a Python dict.
`routed_to_ib: True` is a lie — **no stop-loss has ever rested at IBKR**, and the
bracket-linkage / ActiveBracketRegistry / migration-031 machinery all verify the
simulator against itself. This is why 3 months of green tests never caught it.

Both classes share a duck-typed interface (`safety_layer.py:1771`: "Works for
both IBGatewayConnector (paper) and IBGatewayManager (live)"), so the safety
layer does not need to change — **only what gets attached at `main.py:476`.**

## The decision

What should `self._ib_gateway` be bound to so that a stop actually rests at the
broker, while paper-mode tests stay hermetic and `LIVE_TRADING_ENABLED=False` /
port-4001-blocked invariants hold?

### Option A — Instantiate the real `IBGatewayManager`, bind it at `main.py:476`

Construct `IBGatewayManager` against IB **paper** (port 4002, account
DUP662235) and attach it instead of the connector.

- **Pros:** uses the already-written real client; smallest change to the wiring
  (swap what's constructed at 711 + attached at 476).
- **Cons / ⚠️ must verify first:**
  - ⚠️ Does `IBGatewayManager` actually implement the full interface the safety
    layer calls (`place_bracket_order`, `get_order_status`, `cancel_order`,
    `get_positions`, `is_connected`, `place_paper_order`)? Grep says the type
    hint exists; the method surface must be confirmed against `execution/ib_gateway.py`.
  - ⚠️ Does it connect via `ib_insync`/`ib_async` and is that dependency present
    and working in the engine venv?
  - ⚠️ Bracket-order semantics: does it place a native IB bracket (parent + OCA
    stop/target) or emulate? Native bracket is the whole point (broker-side stop).

### Option B — Promote `IBGatewayConnector` to a real broker client

Make the connector's `connect()` open a real IB paper socket and its order
methods route to IB instead of the mock dict.

- **Pros:** one class, no dual maintenance; existing wiring untouched.
- **Cons:** conflates the test double with the live client; higher risk of a
  test accidentally hitting the broker; loses the value of `IBGatewayManager`
  already existing. Not recommended.

### Option C — Feature-flagged dual binding (recommended shape)

Keep the simulator as the **default/test** path; construct + attach the real
`IBGatewayManager` only when a flag (e.g. `IB_PAPER_BROKER_ENABLED=1`) is set,
so the swap is opt-in and reversible.

```
# main.py, near 476
if settings.IB_PAPER_BROKER_ENABLED and IBGatewayManager is not None:
    gw = IBGatewayManager(host=..., port=4002, client_id=...)   # ⚠️ verify ctor
    await gw.connect()                                           # ⚠️ verify API
    safety_layer.attach_ib_gateway(gw)
else:
    safety_layer.attach_ib_gateway(ib_paper_connector)          # sim (today)
```

- **Pros:** default behavior unchanged (tests stay hermetic, no surprise broker
  traffic); real routing is one env flag; instantly revertible; port 4002 only.
- **Cons:** two paths to keep interface-compatible — but they already are.

## Invariants that constrain every option

- `LIVE_TRADING_ENABLED=False`, `REQUIRE_HUMAN_APPROVAL=True` — unchanged.
- **Port 4001 permanently blocked**; paper is 4002 only.
- Kill-switch logic stays hardcoded Python, no LLM.
- Any change touching `risk/`, `config.py`, or sizing needs `[safety-review]` +
  Tier-3 (Option A/C add a config flag + construction — flag/plumbing is not the
  safety logic, but the PR still carries `[safety-review]` because it changes
  what the safety layer routes to).

## Verification plan (the acceptance that proves it's real)

The current bug survived because verification asked the simulator about itself.
The fix is only "done" when observed against the **broker**, not the process:

1. Place a paper bracket via the pipeline with the real gateway attached.
2. Query **IB Gateway** (not the engine's dict) and confirm a resting STP child
   order exists at the expected stop price, OCA-linked to the parent.
3. Kill/restart the engine; confirm the stop **still rests at IB** (survives a
   process bounce — the property the in-process sim can never have).
4. Cancel via the pipeline; confirm it's gone at IB.
5. `test_safety_layer.py` and the bracket-linkage tests stay green against the
   sim path (flag off) — no hermeticity regression.

## Recommended path

**Option C**, gated behind an env flag, defaulting to the simulator. Sequence:
1. ⚠️ Read `execution/ib_gateway.py` — confirm the method surface + connect API.
   If it's incomplete, finishing it is the real P0 work (not the wiring).
2. Add the flag + construction/attach branch at `main.py:476`.
3. Run the broker-observed verification plan above on port 4002.
4. `[safety-review]` PR; Tier-3 sign-off; then flip the flag in `engine/.env`.

Open question for Amo: is `execution/ib_gateway.py` a working client that just
needs wiring, or a stub? That determines whether P0 is a ~1-day wiring job or a
broker-client build. Answer gates the estimate.
