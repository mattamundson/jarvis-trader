# A-01 Mutation-Spine Static Inventory

**Status:** IN PROGRESS. These are candidate mutation surfaces discovered statically, not proof they are reachable or active.

## Execution candidates

- `engine/execution/ib_gateway.py`
- `engine/execution/ib_gateway_connector.py`
- `engine/execution/ib_order_manager.py`
- `engine/execution/ibkr_executor.py`
- `engine/execution/oms_v2.py`
- `engine/execution/order_router.py`
- `engine/execution/submission_dedup.py`
- broker and position reconcilers under `engine/execution/`

## Required follow-up before A-01 validation

1. Enumerate every API and scheduler caller of place/cancel/replace/flatten operations.
2. Identify composition-time implementation selection and environment guards.
3. Observe process/runtime configuration without exposing secrets.
4. Classify each path as writer, read-only adapter, simulator, test double, or dead code.
5. Confirm local/broker ambiguity and retry behavior.

No listed path is authorized, deprecated, or safe merely because it appears here.
