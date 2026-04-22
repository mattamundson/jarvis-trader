"use client";

import type { OHLCVBar, TechnicalAnalysisResult } from "@/lib/api";

interface StcPanelProps {
  bars?: OHLCVBar[];
  technical?: TechnicalAnalysisResult | null;
  stcOb?: number;
  stcOs?: number;
  height?: number;
}

export function StcIndicatorPanel({
  technical,
  stcOb = 83,
  stcOs = 15,
  height = 100,
}: StcPanelProps) {
  const stcVal = technical?.stc_val;
  const stcSignal = technical?.stc_signal;
  const regime = technical?.regime;

  // Determine needle color based on STC zone
  const stcColor =
    stcVal == null
      ? "#64748b"
      : stcVal >= stcOb
      ? "#ff4466"
      : stcVal <= stcOs
      ? "#00ff88"
      : "#00d4ff";

  return (
    <div
      className="w-full px-3 py-2"
      style={{
        borderTop: "1px solid rgba(0,212,255,0.08)",
        background: "rgba(6,13,26,0.4)",
        height,
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-mono text-slate-500 tracking-widest">
          STC INDICATOR
        </span>
        <div className="flex items-center gap-4">
          {stcVal != null && (
            <span
              className="text-sm font-mono font-bold tabular-nums"
              style={{ color: stcColor }}
            >
              {stcVal.toFixed(1)}
            </span>
          )}
          {stcSignal && (
            <span
              className="text-[10px] font-mono px-2 py-0.5 rounded border tracking-wider"
              style={{
                color: stcSignal.includes("oversold")
                  ? "#00ff88"
                  : stcSignal.includes("overbought")
                  ? "#ff4466"
                  : "#64748b",
                borderColor: stcSignal.includes("oversold")
                  ? "rgba(0,255,136,0.3)"
                  : stcSignal.includes("overbought")
                  ? "rgba(255,68,102,0.3)"
                  : "#334155",
                background: stcSignal.includes("oversold")
                  ? "rgba(0,255,136,0.06)"
                  : stcSignal.includes("overbought")
                  ? "rgba(255,68,102,0.06)"
                  : "transparent",
              }}
            >
              {stcSignal.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* Gauge bar — shows OS/neutral/OB zones with a needle */}
      <div className="relative w-full h-4 rounded overflow-hidden" style={{ background: "rgba(15,23,42,0.8)" }}>
        {/* Oversold zone highlight */}
        <div
          className="absolute top-0 left-0 h-full"
          style={{ width: `${stcOs}%`, background: "rgba(0,255,136,0.12)" }}
        />
        {/* Overbought zone highlight */}
        <div
          className="absolute top-0 right-0 h-full"
          style={{
            width: `${100 - stcOb}%`,
            background: "rgba(255,68,102,0.12)",
          }}
        />
        {/* OS/OB boundary lines */}
        <div
          className="absolute top-0 h-full w-px"
          style={{ left: `${stcOs}%`, background: "rgba(0,255,136,0.3)" }}
        />
        <div
          className="absolute top-0 h-full w-px"
          style={{ left: `${stcOb}%`, background: "rgba(255,68,102,0.3)" }}
        />
        {/* Value needle */}
        {stcVal != null && (
          <div
            className="absolute top-0 h-full w-0.5 transition-all duration-500"
            style={{
              left: `${Math.max(0, Math.min(100, stcVal))}%`,
              backgroundColor: stcColor,
              boxShadow: `0 0 4px ${stcColor}`,
            }}
          />
        )}
        {/* Zone labels */}
        <div className="absolute inset-0 flex items-center justify-between px-1.5">
          <span className="text-[9px] font-mono text-green-700 tracking-wider">
            OS {stcOs}
          </span>
          <span className="text-[9px] font-mono text-slate-700 tracking-wider">
            NEUTRAL
          </span>
          <span className="text-[9px] font-mono text-red-700 tracking-wider">
            OB {stcOb}
          </span>
        </div>
      </div>

      {/* Signal + regime metadata row */}
      <div className="flex items-center gap-3 mt-1.5 flex-wrap">
        {regime && (
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded"
            style={{
              background:
                regime === "TRENDING"
                  ? "rgba(0,255,136,0.1)"
                  : regime === "VOLATILE"
                  ? "rgba(255,68,102,0.1)"
                  : "rgba(0,212,255,0.1)",
              color:
                regime === "TRENDING"
                  ? "#00ff88"
                  : regime === "VOLATILE"
                  ? "#ff4466"
                  : "#00d4ff",
            }}
          >
            {regime}
          </span>
        )}
        {technical?.signal && (
          <span className="text-[10px] font-mono text-slate-400">
            {technical.signal}
          </span>
        )}
        {technical?.direction && technical.direction !== "NEUTRAL" && (
          <span
            className="text-[10px] font-mono font-bold"
            style={{
              color:
                technical.direction === "LONG" ? "#00ff88" : "#ff4466",
            }}
          >
            {technical.direction}
          </span>
        )}
        {technical?.confidence != null && (
          <span className="text-[10px] font-mono text-slate-500">
            conf: {(technical.confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}
