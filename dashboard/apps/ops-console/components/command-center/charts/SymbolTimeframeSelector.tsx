"use client";

import { RefreshCw } from "lucide-react";
import type { ChartSymbol, ChartTimeframe } from "@/hooks/useChartData";

const SYMBOLS: ChartSymbol[] = ["MES", "MCL", "MNQ", "MGC"];
const TIMEFRAMES: ChartTimeframe[] = ["5m", "15m", "1h", "4h", "1d"];

const SYMBOL_LABELS: Record<ChartSymbol, string> = {
  MES: "Micro S&P",
  MCL: "Micro Crude",
  MNQ: "Micro Nasdaq",
  MGC: "Micro Gold",
};

const SYMBOL_STATUS: Record<ChartSymbol, { label: string; color: string }> = {
  MES: { label: "APPROVED", color: "#00ff88" },
  MCL: { label: "APPROVED", color: "#00ff88" },
  MNQ: { label: "APPROVED", color: "#00ff88" },
  MGC: { label: "HALTED", color: "#ff4466" },
};

interface Props {
  symbol: ChartSymbol;
  timeframe: ChartTimeframe;
  onSymbol: (s: ChartSymbol) => void;
  onTimeframe: (tf: ChartTimeframe) => void;
  onRefresh?: () => void;
  isLoading?: boolean;
}

export function SymbolTimeframeSelector({
  symbol,
  timeframe,
  onSymbol,
  onTimeframe,
  onRefresh,
  isLoading,
}: Props) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 border-b"
      style={{ borderColor: "rgba(0,212,255,0.12)", background: "rgba(6,13,26,0.5)" }}
    >
      {/* Symbol selector */}
      <div className="flex items-center gap-1">
        {SYMBOLS.map((s) => {
          const status = SYMBOL_STATUS[s];
          const isActive = s === symbol;
          return (
            <button
              key={s}
              onClick={() => onSymbol(s)}
              className="flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono transition-all"
              style={{
                background: isActive ? "rgba(0,212,255,0.12)" : "transparent",
                color: isActive ? "#00d4ff" : "#475569",
                border: isActive
                  ? "1px solid rgba(0,212,255,0.35)"
                  : "1px solid rgba(71,85,105,0.2)",
              }}
            >
              <span className="font-bold">{s}</span>
              <span
                className="text-[9px] tracking-wider"
                style={{ color: isActive ? status.color : "#334155" }}
              >
                {status.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Divider */}
      <div className="h-5 w-px" style={{ background: "rgba(71,85,105,0.3)" }} />

      {/* Timeframe selector */}
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map((tf) => {
          const isActive = tf === timeframe;
          return (
            <button
              key={tf}
              onClick={() => onTimeframe(tf)}
              className="px-2.5 py-1 rounded text-xs font-mono transition-all"
              style={{
                background: isActive ? "rgba(0,212,255,0.08)" : "transparent",
                color: isActive ? "#00d4ff" : "#475569",
                border: isActive
                  ? "1px solid rgba(0,212,255,0.25)"
                  : "1px solid transparent",
              }}
            >
              {tf}
            </button>
          );
        })}
      </div>

      {/* Divider */}
      <div className="h-5 w-px ml-auto" style={{ background: "rgba(71,85,105,0.3)" }} />

      {/* Label */}
      <div className="text-[10px] font-mono text-slate-600 tracking-wider">
        {SYMBOL_LABELS[symbol]}
      </div>

      {/* Refresh */}
      {onRefresh && (
        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="p-1.5 rounded text-slate-600 hover:text-cyan-400 transition-colors"
          style={{ border: "1px solid rgba(71,85,105,0.2)" }}
          aria-label="Refresh chart data"
        >
          <RefreshCw
            className={`w-3 h-3 ${isLoading ? "animate-spin text-cyan-500" : ""}`}
          />
        </button>
      )}
    </div>
  );
}
