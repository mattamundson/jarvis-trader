"use client";

import useSWR from "swr";
import {
  fetchOpenPositions,
  fetchPnlSnapshot,
  fetchPortfolioSummary,
  type OpenPositionsResponse,
  type PnlSnapshot,
  type PortfolioSummary,
} from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const REFRESH_MS = 15_000;

function pnlColor(v: number | undefined): string {
  if (typeof v !== "number") return "var(--muted-foreground, #9ca3af)";
  if (v > 0) return "#22c55e";
  if (v < 0) return "#ef4444";
  return "var(--muted-foreground, #9ca3af)";
}

/**
 * Same-day P&L reconciliation badge (C3). Shows today's P&L (aggregate from
 * /portfolio/summary), the trustworthy realized sub-number, and open-position
 * count. "Reconciled" is green when the aggregate matches an INDEPENDENTLY
 * computed same-day number (/portfolio/pnl-snapshot) within tolerance — the
 * phantom-day failure mode was drift between these two writers. Fully defensive:
 * when the snapshot can't be compared (no DB / no snapshot / fetch error), the
 * badge reads "unverified" rather than claiming a false reconciliation.
 */
export function SameDayPnLBadge() {
  const { data: summary } = useSWR<PortfolioSummary>(
    "same-day-pnl-summary", fetchPortfolioSummary, { refreshInterval: REFRESH_MS }
  );
  const { data: snapshot } = useSWR<PnlSnapshot>(
    "same-day-pnl-snapshot", fetchPnlSnapshot, { refreshInterval: REFRESH_MS }
  );
  const { data: positions } = useSWR<OpenPositionsResponse>(
    "same-day-pnl-positions", fetchOpenPositions, { refreshInterval: REFRESH_MS }
  );

  const aggregate = summary?.total_daily_pnl;
  const realized = summary?.realized_pnl;
  const unrealized = summary?.unrealized_pnl;
  const snap = snapshot?.daily_pnl;
  const openCount = positions?.count;

  const canReconcile =
    snapshot?.source === "sqlite" &&
    typeof aggregate === "number" &&
    typeof snap === "number";
  const tol = typeof aggregate === "number" ? Math.max(1.0, Math.abs(aggregate) * 0.005) : 1.0;
  const delta =
    typeof aggregate === "number" && typeof snap === "number" ? aggregate - snap : null;
  const reconciled = canReconcile && delta !== null && Math.abs(delta) <= tol;

  const chip = !canReconcile
    ? { bg: "rgba(120,120,120,0.12)", border: "#6b7280", text: "UNVERIFIED" }
    : reconciled
      ? { bg: "rgba(21,128,61,0.14)", border: "#15803d", text: "RECONCILED" }
      : { bg: "rgba(180,83,9,0.16)", border: "#b45309", text: `DRIFT Δ${formatCurrency(Math.abs(delta ?? 0))}` };

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <h2 className="font-mono text-sm font-bold text-foreground">Same-day P&amp;L</h2>
        <span
          className="font-mono text-[10px] font-bold px-2 py-0.5 rounded-full"
          style={{ backgroundColor: chip.bg, border: `1px solid ${chip.border}`, color: chip.border }}
          title={
            canReconcile
              ? `aggregate ${formatCurrency(aggregate ?? 0)} vs snapshot ${formatCurrency(snap ?? 0)} (tol ${formatCurrency(tol)})`
              : "No independent snapshot to compare against (no DB / no snapshot yet)"
          }
        >
          {chip.text}
        </span>
      </div>

      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="font-mono text-2xl font-bold" style={{ color: pnlColor(aggregate) }}>
            {typeof aggregate === "number" ? formatCurrency(aggregate) : "—"}
          </div>
          <div className="font-mono text-[11px] text-muted-foreground mt-0.5">
            realized{" "}
            <span style={{ color: pnlColor(realized) }}>
              {typeof realized === "number" ? formatCurrency(realized) : "—"}
            </span>
            {typeof unrealized === "number" && (
              <>
                {" · unreal "}
                <span style={{ color: pnlColor(unrealized) }}>{formatCurrency(unrealized)}</span>
              </>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-semibold text-foreground">
            {typeof openCount === "number" ? openCount : "—"}
          </div>
          <div className="font-mono text-[10px] text-muted-foreground">open pos</div>
        </div>
      </div>
    </div>
  );
}
