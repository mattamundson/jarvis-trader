# Phase 3 — live trading transition (RETIRED)

> [!CAUTION]
> **Do not execute this runbook.** Legacy Phase 3 criteria are historical
> paper-evidence diagnostics only. They cannot authorize live trading or satisfy
> JARVIS-MIP-1.0 M10/M11. Any future canary requires a separately implemented
> M10/M11 gate, independent safety review, and explicit Tier 3 owner authorization.

## Legacy diagnostic reference only

The legacy criteria remain readable for historical diagnostics. Do not begin
transition work from any result; the CLI is retired and always exits nonzero:

```bash
# With engine running:
curl -H "X-API-Key: <key>" http://127.0.0.1:8010/readiness/phase3

# Standalone CLI (engine not required):
engine/.venv/Scripts/python scripts/phase3_readiness_report.py
# Exit 2=RETIRED/NO-GO (always)
```

The 10 codified criteria (all must pass or be waived by Matt):

| # | Criterion | Severity | Threshold |
|---|-----------|----------|-----------|
| C1 | `paper_trading_window` | BLOCKER | >= 60 calendar days of paper trading |
| C2 | `paper_trades_count` | BLOCKER | >= 100 completed closed trades |
| C3 | `win_rate` | BLOCKER | >= 55% win rate (last 60 days) |
| C4 | `profit_factor` | BLOCKER | >= 1.5 profit factor (last 60 days) |
| C5 | `max_drawdown` | BLOCKER | <= 8% max drawdown from peak (last 60 days) |
| C6 | `sortino_ratio` | BLOCKER | >= 1.0 annualised Sortino (last 60 days) |
| C7 | `consecutive_loss_streak` | WARNING | Max losing streak <= 5 (last 60 days) |
| C8 | `kill_switch_invocations` | BLOCKER | Kill switch triggered <= 2 times (last 60 days) |
| C9 | `engine_uptime_stability` | WARNING | Engine restarts < 1/day avg (last 30 days) |
| C10 | `safety_layer_test_coverage` | BLOCKER | test_safety_layer.py >= 95% line coverage |

The programmatic check is **not an authorization gate**. The checklist below is
retained as historical evidence only and is not an executable transition procedure.

See `docs/runbooks/PHASE3_READINESS_CRITERIA.md` for full detail.

---

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
