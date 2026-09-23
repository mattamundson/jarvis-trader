"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import EngineWidget from "@/components/EngineWidget";
import {
  type HonestTradeSet,
  dailyPnl,
  dedupCaveat,
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
<<<<<<< HEAD
=======
  startingBalanceIsLive: boolean;
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
  // P&L comes from honest deduped set — NOT the raw engine total
  totalPnl: number;
  roi: number;
  tradingDays: number;
  dailyAvgPnl: number;
  annualizedROI: number;
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
  const { honest: honestSet, error: loadError } = useHonestTrades(300_000);
  const honestError = loadError ? (loadError instanceof Error ? loadError.message : "honest trades unavailable") : null;

  // Derive trading days from unique close dates in honest set
  const honestTradingDays = honestSet
    ? new Set(dailyPnl(honestSet.trades).map((d) => d.date)).size
    : null;

  const transformData = (
    json: PaperPhaseSummary,
    honest: HonestTradeSet | null,
  ): ROIState => {
<<<<<<< HEAD
=======
    const startingBalanceIsLive = typeof json.starting_balance === "number";
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    const startingBalance = json.starting_balance ?? STARTING_BALANCE_FALLBACK;

    // P&L: prefer honest deduped net; fall back to raw only if honest unavailable
    const totalPnl = honest !== null ? honest.net : (json.total_pnl ?? 0);

    const roi = startingBalance ? (totalPnl / startingBalance) * 100 : 0;

    // Trading days: prefer honest unique close dates; fall back to raw
    const tradingDays = Math.max(
      honestTradingDays ?? json.trading_days ?? json.days_traded ?? 1,
      1,
    );
    const dailyAvgPnl = totalPnl / tradingDays;
    const annualizedROI = startingBalance
      ? ((dailyAvgPnl * 252) / startingBalance) * 100
      : 0;

<<<<<<< HEAD
    return { startingBalance, totalPnl, roi, tradingDays, dailyAvgPnl, annualizedROI };
=======
    return { startingBalance, startingBalanceIsLive, totalPnl, roi, tradingDays, dailyAvgPnl, annualizedROI };
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
  };

  return (
    <EngineWidget<PaperPhaseSummary>
      endpoint="/portfolio/stats/paper-phase-summary"
      title="Account ROI"
      refreshInterval={300_000}
      render={(json) => {
        const data = transformData(json, honestSet);
        return (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle>Account ROI</CardTitle>
              <Badge variant={badgeVariant(data.roi)}>
                {data.roi >= 0 ? "PROFIT" : "LOSS"}
              </Badge>
            </CardHeader>

            <CardContent>
              {/* Big ROI metric */}
              <div className="flex items-baseline gap-3 mb-4">
                <span
                  className="font-mono text-4xl font-bold tabular-nums"
                  style={{ color: data.roi >= 0 ? "#00ff88" : "#ff4444" }}
                >
                  {data.roi >= 0 ? "+" : ""}{data.roi.toFixed(2)}%
                </span>
                <Badge variant={badgeVariant(data.roi)}>
                  {data.roi >= 5 ? "On Track" : data.roi >= 0 ? "Break Even" : "Drawdown"}
                </Badge>
              </div>

              {/* 2x2 stats grid */}
              <div className="grid grid-cols-2 gap-3 mb-4">
<<<<<<< HEAD
                <StatCell
                  label="Starting Balance"
                  value={`$${data.startingBalance.toLocaleString()}`}
                  valueColor="#888"
                />
=======
                <div className="relative">
                  <StatCell
                    label="Starting Balance"
                    value={`$${data.startingBalance.toLocaleString()}`}
                    valueColor="#888"
                  />
                  {!data.startingBalanceIsLive && (
                    <Badge
                      variant="static"
                      className="absolute top-2 right-2 text-[9px] px-1.5 py-0 leading-4"
                      title="API did not report starting_balance — showing the $10,000 fallback, not the configured account size."
                    >
                      Static
                    </Badge>
                  )}
                </div>
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                <StatCell
                  label="Current P&L"
                  value={fmt$(data.totalPnl)}
                  valueColor={data.totalPnl >= 0 ? "#00ff88" : "#ff4444"}
                />
                <StatCell
                  label="Daily Avg"
                  value={`${fmt$(data.dailyAvgPnl)}/day`}
                  valueColor={data.dailyAvgPnl >= 0 ? "#00ff88" : "#ff4444"}
                />
                <StatCell
                  label="Annualized"
                  value={
                    data.tradingDays >= 5
                      ? `${fmtPct(data.annualizedROI, 1)}/yr`
                      : "Calculating..."
                  }
                  valueColor={
                    data.tradingDays < 5
                      ? "#555"
                      : data.annualizedROI >= 0
                      ? "#00ff88"
                      : "#ff4444"
                  }
                />
              </div>

              {/* Note */}
              <p className="font-mono text-[10px]" style={{ color: "#444" }}>
                Paper account · ${data.startingBalance.toLocaleString()} starting capital
                {data.tradingDays < 5 && " · Annualized projection available after 5 trading days"}
                {honestSet && (
                  <> · {dedupCaveat(honestSet)}</>
                )}
                {honestError && (
                  <> · P&amp;L: raw (honest record unavailable)</>
                )}
              </p>
            </CardContent>
          </Card>
        );
      }}
    />
  );
}
