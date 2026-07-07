# Strategy Lifecycle — Validation-Only Strategies

Companion to `INSTRUMENT_ONBOARDING.md`.
That document covers **instrument-level** gating (by symbol, via `VALIDATION_ONLY_INSTRUMENTS`).
This document covers **strategy-level** gating (by stark_signal / signal type, via `VALIDATION_ONLY_STRATEGIES`).

---

## What is a validation-only strategy?

A strategy signal is validation-only when it has **no completed WFO run** in
`wfe_snapshots` OR its gate v2 verdict is absent or FAIL.

The signal still flows through the full pipeline so its verdicts appear in the
dashboard and Discord briefing feed.  Only the scanner's paper-mode bypass
(`scanner/signal_scanner.py:_scan_symbol`) is blocked — no new paper trades
are submitted.  Existing open positions are **not** force-closed.

---

## Current validation-only strategies (as of 2026-05-21)

| Signal name | Produced by | Reason gated | Gated date | Incident ref |
|---|---|---|---|---|
| `SHORT_GAP_FILL` | `StarkTPOStrategy._get_actionable_signal()` | No WFO run in `wfe_snapshots`; NULL metric fields; gate v2 never evaluated. Root cause of 6 phantom paper trades 2026-05-09 to 2026-05-11 with corrupted price data. | 2026-05-21 | `docs/session-logs/drawdown-root-cause-may-9-to-11.md` |

---

## Lifecycle diagram

```
SIGNAL FIRES (StarkTPO → SHORT_GAP_FILL)
    pipeline runs to completion
    verdict logged → dashboard visible → Discord briefing updated
    scanner gate fires: [VALIDATION_ONLY] log line emitted
    pending_approval row created (audit visibility)
    paper_tracker.add_paper_trade() → BLOCKED (no paper trade)
         |
         v  [all flip-to-active criteria met]
SIGNAL ACTIVE
    pipeline runs → verdict → pending_approval → paper_tracker write → paper trade logged
```

---

## Guard location

The gate is in `scanner/signal_scanner.py:_scan_symbol()`, immediately before
the paper-mode bypass block.  When `stark_signal.upper()` is a member of
`VALIDATION_ONLY_STRATEGIES` (defined in `agents/pipeline.py`), the scanner:

1. Logs a `WARNING`-level `[VALIDATION_ONLY] skipping strategy=<signal> ...` line
2. Short-circuits `_is_paper_mode = False` so the `add_paper_trade` block never runs
3. Still creates the `pending_approval` row so the signal is auditable and visible
   in the dashboard approvals queue

The gate fires **after** the kill-switch check and **after** the pending-approval
row is created.  This means approval-gate blocks (kill switch, `VALIDATION_ONLY_INSTRUMENTS`,
lockouts) take precedence over strategy-level gating when both apply.

**Distinct from `VALIDATION_ONLY_INSTRUMENTS`:**

| Gate | Key | Location | What it blocks |
|---|---|---|---|
| `VALIDATION_ONLY_INSTRUMENTS` | Symbol string (e.g. `"MES"`) | `approval/service.py:ensure_approval_allowed()` | Human-approval API path |
| `VALIDATION_ONLY_STRATEGIES` | Stark signal string (e.g. `"SHORT_GAP_FILL"`) | `scanner/signal_scanner.py:_scan_symbol()` | Scanner paper-mode bypass |

Both gates can co-exist for the same symbol.  The instrument gate is broader
(blocks all orders for that symbol); the strategy gate is narrower (blocks only
trades driven by that specific signal type, regardless of symbol).

---

## Flip-to-active criteria

Remove a signal from `VALIDATION_ONLY_STRATEGIES` when **ALL** of the following are met:

1. **WFE >= 0.6** on a fresh rolling walk-forward run
   (`engine/backtest/rolling_wfe_scheduler.py` — check `wfe_snapshots` for non-NULL metrics)
2. **Gate v2 PASS**: `pf_ci_lower >= 1.10`, `p_edge >= 0.95`, `mc_95th_dd <= 5%`, `dsr >= 0.10`
3. **Tier 3 authorization** from Amo — document in a `[safety-review]` commit

After removal:

```bash
cd engine && .venv/Scripts/python -m pytest \
    tests/test_strategy_validation_only.py \
    tests/test_safety_layer.py -v
```

All tests must pass.  Confirm the `[VALIDATION_ONLY]` log no longer appears in
a manual scan run for the signal before declaring the gate removed.

---

## How to add a new validation-only strategy

1. **Identify the stark_signal value** returned by `StarkTPOStrategy._get_actionable_signal()`
   (or equivalent signal generator).  The value is an UPPER-CASE string such as
   `"SHORT_VAH_REJECT"`, `"LONG_GAP_FILL"`, etc.

2. **Add it to the frozenset** in `engine/agents/pipeline.py`:
   ```python
   VALIDATION_ONLY_STRATEGIES: frozenset[str] = frozenset({
       "SHORT_GAP_FILL",   # gated 2026-05-21 — phantom drawdown incident
       "NEW_SIGNAL_NAME",  # gated YYYY-MM-DD — reason
   })
   ```

3. **Update this runbook** — add a row to the "Current validation-only strategies" table.

4. **Commit with `[safety-review]`** tag (touches strategy registration / order surface).

5. **Run the test suite** — confirm `test_strategy_validation_only.py` passes and
   `test_safety_layer.py` has no regressions.

---

## Interaction with autonomous scanner

When the hourly `SignalScanner` fires and a validation-only stark_signal is present:

- The pending_approval row is still created (`insert_pending_approval` called)
- The `[VALIDATION_ONLY]` WARNING appears in `jarvis_trader.scanner` logger
- `paper_tracker.add_paper_trade` is **not** called
- No paper trade row is written to `paper_trades` table or `paper_trades.json`
- Dashboard: the approval queue shows the pending row, but it cannot be confirmed
  (confirm would route to `approval/service.py:ensure_approval_allowed()`, which
  may raise for instrument-level gating or pass without blocking if the symbol itself
  is order-eligible — in that case only the scanner bypass was blocked, and the
  human-approval path remains open for manual override if Tier 3 authorizes it)

**TL;DR:** `VALIDATION_ONLY_STRATEGIES` closes the automatic paper-trade bypass;
it does not close the manual human-approval path.  If you want to also block
human approval for a specific strategy, you must combine with an entry in
`VALIDATION_ONLY_INSTRUMENTS` or extend `ensure_approval_allowed()`.
