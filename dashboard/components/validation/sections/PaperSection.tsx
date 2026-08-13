"use client";

// Validation workspace — "paper" (live paper-trading evidence) section.
// Extracted verbatim from the former app/validation/page.tsx Sections B and L
// (PRB dashboard-hardening Task 3) — no calculation, label, or error-handling
// behavior changed, only relocated.

import useSWR from "swr";
import { AlertCircle, Clock, CheckCircle2, XCircle, FlaskConical, WifiOff } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";
import type { ValidationReport } from "@/lib/api";
import { PortfolioPLChart } from "@/components/PortfolioPLChart";
import {
  SectionLabel,
  MetricPill,
  honestPerformanceFetcher,
  THRESHOLDS,
  REFRESH_MS,
} from "@/components/validation/shared";

// ── Live Paper Performance Card ───────────────────────────────────────────────

function LivePerformanceCard({ report }: { report: ValidationReport }) {
  const m = report?.metrics;
  // Defense-in-depth: if the engine ever returns a report without metrics,
  // show an honest "unavailable" state instead of crashing the whole page.
  if (!m) {
    return (
      <Card className="border-border">
        <CardContent className="pt-5 pb-5 flex items-center gap-2 text-xs text-muted-foreground">
          <AlertCircle className="h-3.5 w-3.5 text-warn shrink-0" />
          Live paper metrics unavailable — engine returned no performance data.
        </CardContent>
      </Card>
    );
  }
  const isInsufficient = report.status === "INSUFFICIENT_DATA";
  const isPass = report.status === "PASS";
  const isFail = report.status === "FAIL";

  const pfPass = m.profit_factor !== null && m.profit_factor >= THRESHOLDS.profitFactor;
  const ddPass = Math.abs(m.max_drawdown) < THRESHOLDS.maxDrawdown;

  const winRatePct =
    m.win_rate !== null ? `${(m.win_rate * 100).toFixed(1)}%` : "—";
  const ddPct = `${(Math.abs(m.max_drawdown) * 100).toFixed(2)}%`;

  return (
    <Card
      className={
        isPass
          ? "border-bull/20 bg-bull/5"
          : isFail
          ? "border-bear/20 bg-bear/5"
          : "border-border"
      }
    >
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-muted">
            <FlaskConical className="h-4 w-4 text-foreground" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Live Paper Trading
            </p>
            <p className="text-[10px] text-muted-foreground">
              {m.total_trades} trade{m.total_trades !== 1 ? "s" : ""} — {m.period_days} days
            </p>
          </div>

          <span className="ml-auto">
            {isInsufficient && (
              <span className="flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-[11px] font-bold text-muted-foreground tracking-wider">
                <Clock className="h-3.5 w-3.5" />
                COLLECTING DATA
              </span>
            )}
            {isPass && (
              <span className="flex items-center gap-1.5 rounded-full border border-bull/30 bg-bull/10 px-3 py-1 text-[11px] font-bold text-bull tracking-wider">
                <CheckCircle2 className="h-3.5 w-3.5" />
                PASSING VALIDATION
              </span>
            )}
            {isFail && (
              <span className="flex items-center gap-1.5 rounded-full border border-bear/30 bg-bear/10 px-3 py-1 text-[11px] font-bold text-bear tracking-wider">
                <XCircle className="h-3.5 w-3.5" />
                BELOW THRESHOLD
              </span>
            )}
          </span>
        </div>

        {isInsufficient && (
          <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2.5 flex items-start gap-2 mb-4">
            <AlertCircle className="h-3.5 w-3.5 text-warn shrink-0 mt-0.5" />
            <p className="text-xs text-warn leading-relaxed">{report.recommendation}</p>
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Profit Factor
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                isInsufficient
                  ? "text-muted-foreground"
                  : pfPass
                  ? "text-bull"
                  : "text-bear"
              }`}
            >
              {m.profit_factor !== null ? m.profit_factor.toFixed(2) : "—"}
            </p>
            <p className="text-[10px] mt-0.5">
              {!isInsufficient && (
                <span className={pfPass ? "text-bull" : "text-bear"}>
                  {pfPass ? "PASS" : "FAIL"} (need &gt;{THRESHOLDS.profitFactor})
                </span>
              )}
              {isInsufficient && (
                <span className="text-muted-foreground">need {THRESHOLDS.minTrades}+ trades</span>
              )}
            </p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Sharpe Ratio
            </p>
            <p className="tabular-nums text-lg font-bold font-mono text-muted-foreground">
              —
            </p>
            <p className="text-[10px] mt-0.5 text-muted-foreground leading-tight">
              not computed from deduped record
            </p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Win Rate
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                m.win_rate === null
                  ? "text-muted-foreground"
                  : m.win_rate >= 0.55
                  ? "text-bull"
                  : m.win_rate >= 0.45
                  ? "text-warn"
                  : "text-bear"
              }`}
            >
              {winRatePct}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">target ~60%</p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Max Drawdown
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                ddPass ? "text-bull" : "text-bear"
              }`}
            >
              {ddPct}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">limit &lt;10%</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <MetricPill
            label="Total P&L"
            value={formatCurrency(m.total_pnl)}
            color={m.total_pnl >= 0 ? "text-bull" : "text-bear"}
          />
          <MetricPill
            label="Total Trades"
            value={String(m.total_trades)}
          />
          <MetricPill
            label="Avg Win"
            value={m.avg_win !== 0 ? formatCurrency(m.avg_win) : "—"}
            color="text-bull"
          />
          <MetricPill
            label="Avg Loss"
            value={m.avg_loss !== 0 ? formatCurrency(Math.abs(m.avg_loss)) : "—"}
            color="text-bear"
          />
        </div>

        {!isInsufficient && (
          <div
            className={`mt-4 rounded-lg border px-3 py-2.5 text-xs leading-relaxed ${
              isPass
                ? "border-bull/20 bg-bull/5 text-bull"
                : "border-bear/20 bg-bear/5 text-bear"
            }`}
          >
            {report.recommendation}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section — top-level composition ───────────────────────────────────────────

export default function PaperSection() {
  const {
    data: report,
    error: reportError,
    isLoading: reportLoading,
    // Key is a stable string; honestPerformanceFetcher ignores the key and fetches
    // from fetchHonestTrades() which calls the deduped /master/trading/realized endpoint.
  } = useSWR<ValidationReport>("honest-performance", honestPerformanceFetcher, {
    refreshInterval: REFRESH_MS,
  });

  return (
    <div className="space-y-6">
      {reportLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin mr-3" />
          <span className="text-sm text-muted-foreground">Loading performance data...</span>
        </div>
      )}

      {reportError && !reportLoading && (
        <div className="rounded-xl border border-bear/20 bg-bear/5 p-5 flex items-center gap-3">
          <WifiOff className="h-5 w-5 text-bear shrink-0" />
          <div>
            <p className="text-sm font-semibold text-bear">Engine offline or honest trade record unavailable</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Ensure the JARVIS engine is running and reachable through the dashboard proxy, and{" "}
              <code className="font-mono">/master/trading/realized</code> is responding (the deduped trade source).
            </p>
          </div>
        </div>
      )}

      {/* Section B: Live Paper Performance (only when data available) */}
      {!reportLoading && !reportError && report && (
        <section>
          <SectionLabel>B — Live Paper Trading Performance</SectionLabel>
          <LivePerformanceCard report={report} />
        </section>
      )}

      {/* Section L: Portfolio P&L Chart */}
      <section>
        <SectionLabel>L — Portfolio Cumulative P&L</SectionLabel>
        <PortfolioPLChart />
      </section>
    </div>
  );
}
