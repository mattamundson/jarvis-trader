# Paper trading — source of truth (Tier A)

**Goal:** One default ledger for dashboard, alerts, and human decisions. Ambiguity between JSON files, `paper_runner`, and engine DB causes **RISK-006** (dual ledger divergence).

## Default source of truth (explicit)

**Canonical paper ledger:** Engine SQLite at **`engine/data/jarvis_trader.db`** (path relative to process cwd, usually `engine/`). All `/portfolio/*`, `/paper/*`, and safety `system_state` rows live here.

Backups: see [SQLITE_BACKUP.md](SQLITE_BACKUP.md).

## Canonical recommendation (default)

| Surface | Primary source | Notes |
|---------|----------------|--------|
| **Dashboard / API** | Engine **SQLite** + `/portfolio/*` endpoints | Portfolio tracker, paper positions, history |
| **Validation progress** | `/paper/validation/*` and related routers | Aligns with WFE / gate UX |
| **Optional sync** | `paper_runner` → engine POST when `JARVIS_ENGINE_URL` + API key set | See [INTEGRATED_ROADMAP_2026-04.md](../plans/INTEGRATED_ROADMAP_2026-04.md) §1–2 |

## Operator rules

1. **Pick one** path for daily ops and document it in your session log.
2. If you use **both** standalone `paper_runner` files and the engine, run a **periodic reconciliation** (counts, last trade id, or notional) and treat divergence as a **P0 bug**.
3. **IB Gateway paper** remains the broker truth for fills when connected; engine state should **reflect** broker state after sync (see [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md)).

## `/pnl/truth` vs the kill-switch daily-loss number — NOT the same number, by design

Investigated 2026-06-30 (session ROI task #3) after a question about whether
`GET /pnl/truth` (`engine/analytics/pnl_truth.py`) and the kill switch's
daily-loss check (`SafetyLayer` via `PnLMonitor`, `engine/risk/pnl_monitor.py`)
read from the same source of truth. **They intentionally do not, on two axes:**

| | `/pnl/truth` | Kill-switch daily-loss check |
|---|---|---|
| **Window** | Lifetime — sums **every** `paper_trades` row with `status='closed'`, no date filter | Today only — `PnLState.daily_realized_pnl` |
| **Composition** | Realized only | `daily_realized_pnl + daily_unrealized_pnl` (`PnLMonitor.get_daily_pnl()`) |
| **Source priority** | Single read of the `paper_trades` table | Broker (IB Gateway) → SQLite `daily_pnl` snapshots → in-memory tracker |
| **Purpose** | Read-only honest reporting surface; its own docstring states it "never touches... the safety layer" | Live circuit-breaker input — includes unrealized so the kill switch trips on a paper loss before you'd have to close the position to see it |

**Do not wire these together.** `compute_pnl_truth()` supports an optional
`cross_source_pnl` divergence check (tested in `test_pnl_truth.py`), which
looks tempting to point at `PnLMonitor` — don't. Because the windows differ
(lifetime vs today), any account with more than one day of trading history
would show a permanent, spurious divergence and `/pnl/truth` would degrade to
`null` constantly, breaking the exact honesty guarantee it exists to provide.

**Operator takeaway:** it is normal and expected for `/pnl/truth` and the
value that triggered a kill-switch halt to disagree. If you need "why did the
kill switch fire", read `/safety/status` / the loss-tracker, not `/pnl/truth`.
If you need "how has paper trading done overall", `/pnl/truth` is correct and
the kill switch's daily number is not the right comparison.

## Definition of Done (P0-2)

- [x] Default SoT named in this file (**engine/data/jarvis_trader.db**).
- [ ] Dashboard widgets that show paper P&L / positions use that SoT only (audit per release).
- [x] Runbook note: **Engine-only** = default; **paper_runner JSON** = optional hourly loop without FastAPI; **synced** = set `JARVIS_ENGINE_URL` + API key on the paper_runner host so POSTs hit `/portfolio/paper/trade` ([P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) §3).

**Reconciliation helper (operator / CI):** from repo root,

```bash
python scripts/reconcile_paper_sources.py
```

Emits JSON comparing SQLite `paper_trades` counts vs `engine/backtest/results/paper_trades_live.json` length. Exit `1` if SQLite file missing.

## Related

- [07_EXECUTION_SPINE.md](../strategic/07_EXECUTION_SPINE.md) — P0-2
- [PAPER_LEDGER_BOUNDARIES.md](PAPER_LEDGER_BOUNDARIES.md) (if present in repo)
