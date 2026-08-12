"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import EngineWidget from "@/components/EngineWidget";
import {
  type HonestTradeSet,
  dailyPnl,
  dedupCaveat,
  isHonestUnavailable,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// Fallback only — the real figure comes from the API's starting_balance
// (settings.INITIAL_CAPITAL). Hardcoding it made ROI%, P&L and the displayed
// "starting capital" wrong whenever the configured account size wasn't $10k.
const STARTING_BALANCE_FALLBACK = 10_000;

interface PaperPhaseSummary {
  starting_balance?: number;
  current_balance?: number;
  balance?: number;
  total_pnl?: number;
  trading_days?: number;
  days_traded?: number;
}

interface ROIState {
  startingBalance: number;
  // P&L comes from the honest deduped set ONLY. Null when the honest record
  // is unavailable — NEVER falls back to the raw engine total (json.total_pnl),
  // which over-counts re-logged winners (see lib/honestTrades.ts). Every
  // consumer below must render an explicit "unavailable" state on null rather
  // than substituting the raw (inflated) figure.
  totalPnl: number | null;
  roi: number | null;
  tradingDays: number;
  dailyAvgPnl: number | null;
  annualizedROI: number | null;
}

function fmt$(value: number): string {
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(value: number, decimals = 2): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

function badgeVariant(roi: number): "bull" | "info" | "bear" {
  if (roi >= 5) return "bull";
  if (roi >= 0) return "info";
  return "bear";
}

function StatCell({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor: string;
}) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
    >
      <p className="font-mono text-[10px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
        {label}
      </p>
      <p className="font-mono text-sm font-bold tabular-nums" style={{ color: valueColor }}>
        {value}
      </p>
    </div>
  );
}

export function AccountROIWidget() {
  const { honest: honestSet, isLoading: honestLoading } = useHonestTrades(300_000);
  // GT-06 pattern (see lib/honestTrades.ts / scorecard/page.tsx): only "settled
  // with no record" counts as unavailable — not "still loading".
  const honestUnavailable = isHonestUnavailable(honestSet, honestLoading);

  // Derive trading days from unique close dates in honest set
  const honestTradingDays = honestSet
    ? new Set(dailyPnl(honestSet.trades).map((d) => d.date)).size
    : null;

  const transformData = (
    json: PaperPhaseSummary,
    honest: HonestTradeSet | null,
    unavailable: boolean,
  ): ROIState => {
    const startingBalance = json.starting_balance ?? STARTING_BALANCE_FALLBACK;

    // P&L: ONLY the honest deduped net. Never fall back to json.total_pnl
    // (raw engine total) — that field over-counts re-logged winners and would
    // silently inflate the headline ROI%. Null means "unavailable", not zero.
    const totalPnl = unavailable ? null : (honest?.net ?? 0);

    const roi =
      totalPnl === null ? null : startingBalance ? (totalPnl / startingBalance) * 100 : 0;

    // Trading days: prefer honest unique close dates; fall back to raw
    const tradingDays = Math.max(
      honestTradingDays ?? json.trading_days ?? json.days_traded ?? 1,
      1,
    );
    const dailyAvgPnl = totalPnl === null ? null : totalPnl / tradingDays;
    const annualizedROI =
      dailyAvgPnl === null
        ? null
        : startingBalance
        ? ((dailyAvgPnl * 252) / startingBalance) * 100
        : 0;

    return { startingBalance, totalPnl, roi, tradingDays, dailyAvgPnl, annualizedROI };
  };

  return (
    <EngineWidget<PaperPhaseSummary>
      endpoint="/portfolio/stats/paper-phase-summary"
      title="Account ROI"
      refreshInterval={300_000}
      render={(json) => {
        const data = transformData(json, honestSet, honestUnavailable);
        return (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle>Account ROI</CardTitle>
              <Badge variant={data.roi === null ? "info" : badgeVariant(data.roi)}>
                {data.roi === null ? "DATA UNAVAILABLE" : data.roi >= 0 ? "PROFIT" : "LOSS"}
              </Badge>
            </CardHeader>

            <CardContent>
              {/* Big ROI metric */}
              <div className="flex items-baseline gap-3 mb-4">
                <span
                  className="font-mono text-4xl font-bold tabular-nums"
                  style={{ color: data.roi === null ? "#888" : data.roi >= 0 ? "#00ff88" : "#ff4444" }}
                >
                  {data.roi === null
                    ? "—"
                    : `${data.roi >= 0 ? "+" : ""}${data.roi.toFixed(2)}%`}
                </span>
                <Badge variant={data.roi === null ? "info" : badgeVariant(data.roi)}>
                  {data.roi === null
                    ? "Unavailable"
                    : data.roi >= 5
                    ? "On Track"
                    : data.roi >= 0
                    ? "Break Even"
                    : "Drawdown"}
                </Badge>
              </div>

              {/* 2x2 stats grid */}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <StatCell
                  label="Starting Balance"
                  value={`$${data.startingBalance.toLocaleString()}`}
                  valueColor="#888"
                />
                <StatCell
                  label="Current P&L"
                  value={data.totalPnl === null ? "—" : fmt$(data.totalPnl)}
                  valueColor={
                    data.totalPnl === null ? "#555" : data.totalPnl >= 0 ? "#00ff88" : "#ff4444"
                  }
                />
                <StatCell
                  label="Daily Avg"
                  value={data.dailyAvgPnl === null ? "—" : `${fmt$(data.dailyAvgPnl)}/day`}
                  valueColor={
                    data.dailyAvgPnl === null
                      ? "#555"
                      : data.dailyAvgPnl >= 0
                      ? "#00ff88"
                      : "#ff4444"
                  }
                />
                <StatCell
                  label="Annualized"
                  value={
                    data.annualizedROI === null
                      ? "—"
                      : data.tradingDays >= 5
                      ? `${fmtPct(data.annualizedROI, 1)}/yr`
                      : "Calculating..."
                  }
                  valueColor={
                    data.annualizedROI === null
                      ? "#555"
                      : data.tradingDays < 5
                      ? "#555"
                      : data.annualizedROI >= 0
                      ? "#00ff88"
                      : "#ff4444"
                  }
                />
              </div>

              {/* Note */}
              <p
                className="font-mono text-[10px]"
                style={{ color: honestUnavailable ? "#ffaa00" : "#444" }}
              >
                Paper account · ${data.startingBalance.toLocaleString()} starting capital
                {!honestUnavailable &&
                  data.tradingDays < 5 &&
                  " · Annualized projection available after 5 trading days"}
                {honestSet && !honestUnavailable && (
                  <> · {dedupCaveat(honestSet)}</>
                )}
                {honestUnavailable && (
                  <>
                    {" "}
                    · Honest P&amp;L record unavailable — figures hidden rather than shown from
                    the raw (inflated) total
                  </>
                )}
              </p>
            </CardContent>
          </Card>
        );
      }}
    />
  );
}
