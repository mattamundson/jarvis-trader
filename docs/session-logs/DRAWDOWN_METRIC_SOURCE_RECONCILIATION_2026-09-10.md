# Drawdown Metric-Source Reconciliation — Diagnostic (read-only, 2026-09-10 ~11:50 CDT)

**Cron tick:** jarvis-control-plane-recovery-loop v1 (5a6762293081), tick 23.
**Scope:** docs/evidence only. No engine, risk, kill-switch, or .env changes. Fix requires a [safety-review] PR.

## Symptom (standing since 09-10 ~05:50 tick)

- `AlertManager` emits `DRAWDOWN CRITICAL -12.5%` via Discord every engine session.
- `MarginMonitor` concurrently reports drawdown 0.0% with equity $13,181.32.
- `/safety/health` endpoints require auth (401 unauth) — values cross-checked via logs + SQLite.

## Call chains verified in code

1. **AlertManager path (the -12.5%)**
   `main.py:1750-1752` → `AlertManager(notify_fn=_oc_send_raw).start()` + `safety_layer.inject_alert_manager()`
   → `safety_layer.sync_from_broker()` (`risk/safety_layer.py:2338-2380`, called every 60s)
   → `drawdown_pct = self._pnl_monitor.get_drawdown_pct()` (`risk/pnl_monitor.py:161`)
   → `get_current_pnl_state()` prefers **SQLite today row** (`pnl_monitor.py:114-117`)
   → `get_peak_balance()` (`pnl_monitor.py:344`): **90-day trailing high-water mark** of
   `daily_pnl.ending_balance` (PEAK_LOOKBACK_DAYS=90, PLAUSIBLE_PEAK_MULTIPLE=5 guard).
   → `AlertManager.check_and_alert()` fires `drawdown_10pct` threshold (`alert_thresholds.py:16` = -0.10).

2. **MarginMonitor path (the 0.0%)**
   `risk/margin_monitor.py:69-74`: `_peak_equity` is an **in-process accumulator seeded at 0.0 on engine start**;
   peak only rises while the process lives. Equity has been flat at $13,181.32 since the
   09-10 08:36 engine restart → peak == current → 0.0%.

## Evidence (SQLite `engine/data/jarvis_trader.db`, read-only query)

- `daily_pnl` trailing 90d max `ending_balance` = **$15,057.8928 on 2026-08-03**
  (window also holds 15,727.72 on 2026-07-22 — that is >90d back at query time relative to
  the 08-03 peak logic; both peaks are July-August paper P&L highs).
- Current equity (`pnl_snapshots` 2026-09-10): **$13,181.3161**, daily_pnl 0.0, peak_equity 13,181.3161.
- Computed: (13,181.3161 − 15,057.8928) / 15,057.8928 = **−12.46%** → AlertManager prints −12.5%. Matches exactly.
- Restart timeline correlation: alerts at 06:03 and 08:38 bracket the 08:36-08:37 restart;
  AlertManager dedup (`_fired_today`, `alert_manager.py:90,150`) is **in-memory only** → every restart re-fires the alert.

## Verdict

**Not a data bug — two different drawdown definitions running simultaneously:**

| Source | Peak semantics | Value |
|---|---|---|
| AlertManager (via pnl_monitor) | SQLite trailing-90d paper-account high-water mark | **−12.5%** (real paper-account drawdown from the 2026-08-03 peak) |
| MarginMonitor | Process-lifetime peak (resets every restart) | **0.0%** (meaningless across restarts) |

The −12.5% is arithmetically correct for the paper account vs its recent peak. MarginMonitor's
0% is the misleading number (process-scoped, restart-reset). The alert is *real signal repeated*
(daily dedup, re-fired by restarts) rather than a false positive — but the two surfaces disagreeing
masks that and adds noise.

## Recommended fix (requires [safety-review] PR — NOT executed here)

1. **Single metric source:** route MarginMonitor's `drawdown_pct` through
   `pnl_monitor.get_drawdown_pct()` (persisted 90d peak) so both surfaces report the same number.
2. **Durable dedup (optional):** persist `_fired_today` per threshold+date (SQLite) so restarts
   stop re-firing same-day alerts.
3. Acceptance: `/safety/circuit-breakers` and MarginMonitor report identical drawdown_pct;
   one alert per threshold per day across restarts.

## Boundaries respected

- No changes to `risk/`, `.env`, kill-switch, or thresholds.
- DB accessed read-only (`mode=ro`).
