# [safety-review] Paper IBKR port alignment

## Change

Local runtime config `engine/.env` is aligned from:

```text
LIVE_TRADING_ENABLED=False
IBKR_PORT=4001
```

to:

```text
LIVE_TRADING_ENABLED=False
IBKR_PORT=4002
```

`engine/.env` is gitignored, so this review note is the tracked audit artifact for the local runtime change.

## Safety impact

- Runtime behavior changes the IBKR API target away from live port `4001` and onto paper port `4002`.
- This tightens the paper-phase invariant; it does **not** enable live trading.
- `LIVE_TRADING_ENABLED` remains `False`.
- No kill-switch thresholds, risk caps, position sizing, order routing logic, or LLM safety decision paths are changed.
- Existing startup checks already enforce this invariant and refuse `IBKR_PORT=4001` during paper phase.

## Invariants checked

- `LIVE_TRADING_ENABLED=False` stays unchanged.
- `IBKR_PORT=4002` matches `.claude/rules/safety.md` and `docs/runbooks/SAFETY_REVIEW_RITUAL.md`.
- Port `4001` remains blocked for paper phase by `engine/startup_checks.py`.
- This change may leave IB data disconnected if TWS/IB Gateway paper API is not listening on `4002`; that is operationally safer than connecting a paper-phase engine to live port `4001`.

## Verification plan

1. Update ignored `engine/.env` only for `IBKR_PORT`.
2. Stop the temporary process-level override engine.
3. Run `restart_engine.ps1` normally.
4. Verify `/health` via direct engine and dashboard proxy shows:
   - `paper_mode: true`
   - `live_trading: false`
   - `ibgateway_port: 4002`
5. Confirm `4001` may still be the only local TWS/IBG listener; if so, health should show IBG/data disconnected rather than silently using live port.
