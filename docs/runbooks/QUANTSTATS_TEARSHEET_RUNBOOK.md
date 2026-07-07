# QuantStats Tearsheet — Operations Runbook

**Code:** `engine/reports/quantstats_metrics.py` (commit `c80a9ca`), wired via `engine/routers/reports_router.py` (commit `250b25a`). Dashboard widget: `dashboard/components/QuantStatsPanel.tsx` (commit `051ffe1`).

---

## 1. Overview

`GET /reports/quantstats` returns a pure-JSON portfolio metrics payload — no HTML, no chart rendering. It is the canonical source for all tearsheet numbers surfaced in the dashboard's **Performance** page. The `<QuantStatsPanel>` component renders the payload without any external chart library (inline SVG only).

---

## 2. File map

### Backend

| File | Purpose |
|------|---------|
| `engine/reports/quantstats_metrics.py` | New module — `compute_quantstats_metrics`, `_load_pnl_series`, `_monthly_returns`, `_rolling_sharpe_30d` |
| `engine/routers/reports_router.py` | Extended with the `/quantstats` route |
| `engine/tests/test_quantstats_metrics.py` | 9 unit tests |
| `engine/requirements-core.txt` | `quantstats==0.0.81` pinned (commit `df6600b`) |

### Frontend

| File | Purpose |
|------|---------|
| `dashboard/lib/api.ts` | `QuantStatsMetrics` interface + `fetchQuantStats()` helper (commit `ea07d90`) |
| `dashboard/components/QuantStatsPanel.tsx` | 371-line panel — headline grid, heatmap, SVG sparkline |
| `dashboard/app/performance/page.tsx` | Mounts `<QuantStatsPanel>` above `<AccountROIWidget>` |

---

## 3. API contract

```
GET /reports/quantstats?run_id=<optional>&days=<7..365>
X-API-Key: <value from engine/.env>
```

**Response shape:**

| Field | Type | Notes |
|-------|------|-------|
| `n_trades` | `int` | Closed trades in the requested window |
| `start_date` | `"YYYY-MM-DD"` | Earliest date in the series |
| `end_date` | `"YYYY-MM-DD"` | Latest date in the series |
| `source` | `"pnl_snapshots" \| "paper_trades"` | Which table supplied the series |
| `sortino` | `float \| null` | Annualized Sortino ratio (252-day basis) |
| `sharpe` | `float \| null` | Annualized Sharpe ratio (252-day basis) |
| `calmar` | `float \| null` | Annualized return ÷ max drawdown |
| `max_dd` | `float \| null` | Peak-to-trough drawdown, expressed as a negative fraction |
| `max_dd_duration_days` | `int \| null` | Calendar days from drawdown peak to recovery |
| `win_rate` | `float \| null` | Fraction of trades that closed profitable |
| `profit_factor` | `float \| null` | Gross profit ÷ gross loss |
| `monthly_returns` | `{ "YYYY-MM": float, ... }` | Month-keyed return fractions |
| `rolling_sharpe_30d` | `[{ "date": "YYYY-MM-DD", "value": float }, ...]` | 30-day rolling Sharpe, one entry per trading day |

All scalar metrics are `null` when QuantStats cannot compute a value (zero variance, fewer than 2 data points, or division by zero).

---

## 4. Data source priority

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 | `pnl_snapshots` table | Has rows with `date`, `daily_pnl`, `portfolio_equity` |
| 2 | `paper_trades` table | Fallback — daily PnL aggregated by `exit_time::date` |

Annualization constant is **252 trading days** throughout both paths.

---

## 5. Smoke test (paste-ready PowerShell)

```powershell
$key = (Select-String -Path 'engine\.env' -Pattern '^API_KEY=').Line -replace '^API_KEY='
Invoke-RestMethod 'http://127.0.0.1:8010/reports/quantstats?days=90' `
    -Headers @{ 'X-API-Key' = $key }
```

Expected: HTTP 200, JSON object with `source`, `n_trades`, and scalar fields (may be `null` with a thin trade history).

---

## 6. Known artifacts — first live run (2026-05-20, 23 trades)

| Artifact | Cause | Disposition |
|----------|-------|-------------|
| Calmar returns 26-trillion | Max drawdown is near-zero (denominator → 0) | Mathematically correct; statistically meaningless below ~100 trades |
| Sortino inflates similarly | Low downside-variance window | Same root cause — thin sample |
| `rolling_sharpe_30d` returns `[]` | Data window < 30 days | Expected; array populates once 30 daily rows exist |
| All scalars `null` | Zero closed trades in requested window | Lower `days` param or wait for more paper trades to close |

Scalars normalize as trade count grows. Treat any single metric as advisory until `n_trades >= 100`.

---

## 7. Dashboard panel UX

- **Time-range select:** 30d / 90d / 180d / 365d — defaults to 90d on mount.
- **Headline grid:** Sortino, Sharpe, Calmar, Max DD, DD Duration, Win Rate, Profit Factor. `null` values render as `—`.
- **Badge thresholds** (Sortino, Sharpe, Calmar, Profit Factor):

  | Value | Badge variant |
  |-------|--------------|
  | ≥ 1.5 | `bull` |
  | < 0 | `bear` |
  | otherwise | `neutral` |

- **Monthly returns:** HTML table heatmap (no chart lib).
- **Rolling 30d Sharpe:** 600×80 inline SVG — polyline, fill, zero-reference line.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `404 Not Found` on `/reports/quantstats` | Router not mounted | Verify `main.py` imports `reports_router` and calls `app.include_router(reports_router)` |
| `500` with `ModuleNotFoundError: quantstats` | Package not installed in venv | `engine/.venv/Scripts/pip install -r requirements-core.txt` |
| All scalar metrics `null` | `pnl_snapshots` empty and no closed `paper_trades` in window | Reduce `days` param until at least one closed trade is in range; or check DB has rows |
| `rolling_sharpe_30d` always `[]` | Fewer than 30 daily rows in the selected window | Expected behavior; extend window or wait for more trading days |
| Calmar / Sortino in the billions | Near-zero drawdown or downside variance | Not a bug — suppress display below a trade-count threshold (e.g. `n_trades < 50`) |
| Dashboard panel shows all `—` | `fetchQuantStats()` returned null or threw | Check browser console; engine may be returning 401 (stale API key) or 500 |

---

## 9. Router mount verification

If the endpoint is missing after an engine restart, confirm the import chain in `engine/main.py`:

```python
from routers.reports_router import router as reports_router
app.include_router(reports_router, prefix="/reports", tags=["reports"])
```

Fix commit `250b25a` added this. If it regresses, re-apply.

---

## 10. Related runbooks

- `[[PAPER_TRADING]]` — paper trade lifecycle and `paper_trades` table schema
- `[[HEALTH_API_CONTRACT]]` — engine auth headers and stable API key names
- `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]` — scheduled research pipeline that may generate `pnl_snapshots` rows
