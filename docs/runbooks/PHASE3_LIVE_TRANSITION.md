# Phase 3 — live trading transition (runbook)

## Preconditions (Tier 3)

- Paper validation gates met (PF, Sharpe, win rate, trade count, days, drawdown per `CLAUDE.md`).
- `/review` completed for any change touching `safety_layer.py`, `config.py` risk fields, `signals.py`, or broker connectors.
- IB Gateway **paper** proven stable; **no** production orders on port **4001** until explicit sign-off.

## Change control

1. **`LIVE_TRADING_ENABLED`**: flip only in a controlled release with rollback plan; default remains `False` until sign-off.
2. **`REQUIRE_HUMAN_APPROVAL`**: keep `True` unless product explicitly documents removal and Risk signs off.
3. **`ALLOW_PAPER_SIMULATED_ORDERS`**: understand interaction with live mode in `safety_layer.check_order` before changing.

## Operational checklist

- Kill switch and drawdown limits unchanged (-2% daily / -10% drawdown per project policy).
- Human approval UI / pending approvals workflow exercised on staging.
- Rollback: revert config flags, restart engine (`restart_engine.ps1`), confirm `GET /safety/status`.

## Approvals

- Designate who may approve live enablement (owner + risk). Log date and ticket/PR in session log.
