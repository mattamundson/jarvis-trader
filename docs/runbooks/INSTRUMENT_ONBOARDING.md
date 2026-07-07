# Instrument onboarding (futures)

## Steps

1. **Watchlist** — Add symbol to `FUTURES_WATCHLIST` in `engine/config.py` (or env), aligned with capital and risk limits.
2. **Signals** — If bar interval or regime logic differs, update canonical parameters in `engine/backtest/signals.py` (Tier 3 change — review required).
3. **Walk-forward / WFE** — Run rolling WFE and backtest scripts; record WFE and verdict in `engine/backtest/paper_config.py` (or equivalent status source) and dashboard paper-status endpoint.
4. **Paper config** — Ensure `paper_config` / validation tracker entries match approved TF and status (`ACTIVE` vs halted).
5. **Dashboard** — Confirm command center and validation pages show the new row; no auto-live until status APPROVED.
6. **Pipeline** — Run `POST /pipeline/run` in paper; if `requires_human` is true, use **Pending approvals** page before ledger entries.

## Do not skip

- MES-class WFE failures (below gate) must remain **DO NOT TRADE** until re-validated.

---

## Validation-only instruments (MES, MGC)

Some instruments are included in `FUTURES_WATCHLIST` for pipeline signal generation and
dashboard visibility, but are blocked from generating paper orders. This is the
**validation-only** state, codified as `VALIDATION_ONLY_INSTRUMENTS` in
`engine/agents/pipeline.py`.

### Current validation-only instruments (as of 2026-05-24)

`VALIDATION_ONLY_INSTRUMENTS` is currently **empty** — MES and MGC were promoted
from validation-only to active paper trading on 2026-05-24 (Tier-3 auth, gate v2
ALT PASS: MES p_edge 0.75, MGC p_edge 0.6842). No instrument is in the
validation-only state right now.

| Symbol | Status | Note |
|--------|--------|------|
| MES | ACTIVE (promoted 2026-05-24) | was validation-only Wave 3 (2026-05-21) |
| MGC | ACTIVE (promoted 2026-05-24) | was validation-only Wave 3 (2026-05-21) |

### Lifecycle

```
WATCHLIST + VALIDATION_ONLY
    pipeline runs → verdict logged → dashboard/briefing updated
    approval gate blocks paper orders (HTTP 409)
         |
         v  [WFE >= 0.6 + gate v2 PASS + Tier 3 auth]
WATCHLIST + ORDER_ELIGIBLE
    pipeline runs → verdict → human approval → paper order submitted
```

### Guard location

The block is in `approval/service.py:ensure_approval_allowed()`. If a human-approval
API call arrives for a validation-only symbol, it returns HTTP 409 with a message
referencing `VALIDATION_ONLY_INSTRUMENTS` and the flip-to-active criteria.

The guard fires **after** the kill-switch check and **after** the watchlist membership
check, so the safety layer's canonical `DO_NOT_TRADE_SYMBOLS` always wins if there is
ever an overlap (there should never be — `DO_NOT_TRADE_SYMBOLS` blocks signal generation
entirely; `VALIDATION_ONLY_INSTRUMENTS` blocks order submission only).

### Flip-to-active criteria

Remove a symbol from `VALIDATION_ONLY_INSTRUMENTS` when ALL of the following are met:

1. WFE >= 0.6 on a fresh rolling walk-forward run (use `engine/backtest/rolling_wfe_scheduler.py`)
2. Gate v2 PASS: `pf_ci_lower >= 1.10`, `p_edge >= 0.95`, `mc_95th_dd <= 5%`, `dsr >= 0.10`
3. Explicit Tier 3 authorization from Amo (document in a `[safety-review]` commit)

After removal, re-run the test suite (`pytest engine/tests/test_validation_only_instruments.py`)
to confirm the constant and approval gate reflect the updated state.

### Interaction with autonomous scheduler

When `ENABLE_AUTONOMOUS_PIPELINE=1` (env flag), validation-only instruments will still
appear in the candidate generation loop and produce scored verdicts. However, because
they cannot enter the approval queue (the queue only receives non-HOLD verdicts for
order-eligible symbols), their candidates will never reach the approval queue. Verdict
events still fire on the event bus (`pipeline_run` events), so the dashboard and
Discord briefing see them. This is the intended behavior — validation-only instruments
generate observable signal history without consuming approval queue capacity.
