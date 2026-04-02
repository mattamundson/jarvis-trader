# Patch bundle — trading-days + streak dedupe + TradingDaysCountdownCard

**Plan mode blocked automated edits to code.** Do one of:

1. Switch this chat to **Agent** mode and say: *Apply IMPLEMENTATION_PATCH_trading_days_2026-04-02*
2. Or apply the sections below manually.

---

## 1. `engine/main.py` (insert before final `# ───` line)

After `get_weekly_stats` ends with `raise HTTPException(status_code=500, detail=str(e)) from e`, add:

```python
@app.get("/portfolio/stats/trading-days")
async def get_trading_days_stats():
    """
    Distinct calendar days with at least one closed paper exit (SQLite).

    Aliases match dashboard consumers: TradingDaysCountdownCard, ValidationChecklist.
    """
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    threshold = 30
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(DISTINCT DATE(exit_time)) AS td
                FROM paper_trades
                WHERE LOWER(TRIM(status)) = 'closed'
                  AND exit_time IS NOT NULL
                """
            )
            row = cursor.fetchone()
            conn.close()

        n = int(row["td"] or 0) if row else 0
        return {
            "trading_days": n,
            "trading_days_completed": n,
            "days_traded": n,
            "completed_days": n,
            "threshold": threshold,
            "threshold_met": n >= threshold,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
```

---

## 2. `engine/routers/portfolio_router.py`

Delete the whole `@router.get("/stats/streaks")` / `async def streak_stats():` … function (ends before `def _parse_trade_day`).

Replace with one line:

```python
# GET /portfolio/stats/streaks — canonical handler is on the FastAPI app in main.py (StreakBadge).
```

---

## 3. Replace full file `dashboard/components/TradingDaysCountdownCard.tsx`

```tsx
"use client";

import React, { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";

interface TradingDaysStats {
  trading_days: number;
  threshold: number;
  threshold_met: boolean;
}

interface PaperPhaseSummary {
  total_return_pct: number;
  total_pnl: number;
  validation_status?: string;
}

export function TradingDaysCountdownCard() {
  const [tradingDays, setTradingDays] = useState(0);
  const [threshold, setThreshold] = useState(30);
  const [returnPct, setReturnPct] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [validationStatus, setValidationStatus] = useState("in_progress");

  async function fetchData() {
    try {
      const [daysRes, summaryRes] = await Promise.allSettled([
        fetchEngine<TradingDaysStats>(`/portfolio/stats/trading-days`),
        fetchEngine<PaperPhaseSummary>(`/portfolio/stats/paper-phase-summary`),
      ]);

      if (daysRes.status === "fulfilled") {
        const data = daysRes.value;
        setTradingDays(data.trading_days ?? 0);
        setThreshold(data.threshold ?? 30);
      }

      if (summaryRes.status === "fulfilled") {
        const data = summaryRes.value;
        setReturnPct(data.total_return_pct ?? 0);
        setTotalPnl(data.total_pnl ?? 0);
        setValidationStatus(
          (data.validation_status ?? "IN_PROGRESS").toLowerCase()
        );
      }
    } catch {
      // silently use defaults on error
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Validation Progress</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-6">
          <div className="text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Trading Days</p>
            <div className="relative inline-flex items-center justify-center">
              <span
                className={cn(
                  "text-5xl font-mono font-bold",
                  tradingDays >= threshold
                    ? "text-green-400"
                    : tradingDays >= threshold * 0.67
                      ? "text-yellow-400"
                      : ""
                )}
              >
                {tradingDays}
              </span>
            </div>
            <p className="text-sm text-muted-foreground mt-1">of {threshold} days</p>
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden mt-2">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  tradingDays >= threshold ? "bg-green-500" : "bg-accent"
                )}
                style={{
                  width: `${Math.min(100, threshold > 0 ? (tradingDays / threshold) * 100 : 0)}%`,
                }}
              />
            </div>
            <Badge variant={tradingDays >= threshold ? "bull" : "warn"} className="mt-2">
              {tradingDays >= threshold
                ? "TARGET MET"
                : `${Math.max(0, threshold - tradingDays)} days left`}
            </Badge>
          </div>

          <div className="space-y-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Phase Timeline</p>
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Paper Phase</span>
              <Badge variant="warn">Apr–May 2026</Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Live Gate</span>
              <Badge variant="neutral">Jun 2026</Badge>
            </div>
            <div className="flex justify-between items-center border-t border-border pt-2">
              <span className="text-xs text-muted-foreground">Return So Far</span>
              <span
                className={cn(
                  "text-sm font-mono font-medium",
                  returnPct > 0 ? "text-green-400" : returnPct < 0 ? "text-red-400" : ""
                )}
              >
                {returnPct >= 0 ? "+" : ""}
                {returnPct.toFixed(2)}%
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Total P&amp;L</span>
              <span
                className={cn(
                  "text-sm font-mono font-medium",
                  totalPnl > 0 ? "text-green-400" : totalPnl < 0 ? "text-red-400" : ""
                )}
              >
                {totalPnl >= 0 ? "+$" : "-$"}
                {Math.abs(totalPnl).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Status</span>
              <Badge
                variant={
                  validationStatus === "review_ready" || validationStatus === "passed"
                    ? "bull"
                    : validationStatus === "failed"
                      ? "bear"
                      : "warn"
                }
              >
                {validationStatus === "review_ready"
                  ? "REVIEW READY"
                  : validationStatus === "no_trades"
                    ? "NO TRADES"
                    : validationStatus === "no_tracker"
                      ? "NO TRACKER"
                      : validationStatus === "passed"
                        ? "PASSED"
                        : validationStatus === "failed"
                          ? "FAILED"
                          : "IN PROGRESS"}
              </Badge>
            </div>
          </div>
        </div>

        <p className="text-xs text-muted-foreground mt-4">
          Target: 30 trading days with PF≥2.0, Sharpe≥1.5 • Refreshes every 5m
        </p>
      </CardContent>
    </Card>
  );
}
```

---

## 4. `engine/tests/test_routes_wired.py`

Inside `expected_routes` dict, add (e.g. after paper-phase-summary if present, or after portfolio summary):

```python
        ("GET", "/portfolio/stats/trading-days"): "distinct trading days (validation UI)",
```

---

## Verify

```powershell
curl.exe -s -H "X-API-Key: YOUR_KEY" http://127.0.0.1:8010/portfolio/stats/trading-days
cd c:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard; pnpm run build
cd c:\Users\mattm\ThinkorSwim\jarvis-trader\engine; .\.venv\Scripts\ruff.exe check main.py routers\portfolio_router.py
.\.venv\Scripts\python.exe -m pytest tests\test_routes_wired.py tests\test_api_contract_minimal.py -q --tb=no
```

Restart uvicorn after `main.py` / `portfolio_router.py` changes.
