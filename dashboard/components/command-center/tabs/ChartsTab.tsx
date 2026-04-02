"use client";
import { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { useChartData, type ChartSymbol, type ChartTimeframe } from "@/hooks/useChartData";
import { useOptionsChain } from "@/hooks/useOptionsChain";
import { useWebSocket } from "@/hooks/useWebSocket";
import { SymbolTimeframeSelector } from "../charts/SymbolTimeframeSelector";
import { OptionsChainPanel } from "../charts/OptionsChainPanel";

// Dynamic imports for chart components (avoid SSR issues with canvas/WebGL)
const CandlestickChart = dynamic(
  () => import("../charts/CandlestickChart").then((m) => ({ default: m.CandlestickChart })),
  {
    ssr: false,
    loading: () => (
      <div className="h-[440px] flex items-center justify-center text-slate-500 text-sm font-mono">
        Initializing chart...
      </div>
    ),
  }
);
const StcIndicatorPanel = dynamic(
  () => import("../charts/StcIndicatorPanel").then((m) => ({ default: m.StcIndicatorPanel })),
  { ssr: false }
);
const RegimeTimeline = dynamic(
  () => import("../charts/RegimeTimeline").then((m) => ({ default: m.RegimeTimeline })),
  { ssr: false }
);

type ViewMode = "chart" | "options";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function ChartsTab({ data }: { data: any }) {
  const [symbol, setSymbol] = useState<ChartSymbol>("MCL");
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("1h");
  const [viewMode, setViewMode] = useState<ViewMode>("chart");

  const {
    bars,
    barsLoading,
    technical,
    technicalLoading,
    regime,
    currentSignal,
    pipelineHistory,
    isLoading,
  } = useChartData(symbol, timeframe);

  const { chain, chainLoading, greeks } = useOptionsChain(symbol);

  // ── WebSocket: live price ticks ───────────────────────────────────────────
  const [livePrice, setLivePrice] = useState<number | null>(null);

  // Reset live price when symbol changes
  useEffect(() => {
    setLivePrice(null);
  }, [symbol]);

  const { connected: wsConnected } = useWebSocket((event) => {
    if (event.type === "price_update" && event.symbol === symbol) {
      setLivePrice(event.price);
    }
  });

  // SWR handles caching; manual refresh is a no-op trigger
  const handleRefresh = useCallback(() => {}, []);

  return (
    <div className="space-y-4">
      {/* View mode toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode("chart")}
          className={`px-4 py-1.5 text-xs font-mono rounded transition-all ${
            viewMode === "chart"
              ? "bg-cyan-900/60 text-cyan-400 border border-cyan-700/60"
              : "text-slate-500 hover:text-slate-300 border border-slate-700/40"
          }`}
        >
          PRICE CHART
        </button>
        <button
          onClick={() => setViewMode("options")}
          className={`px-4 py-1.5 text-xs font-mono rounded transition-all ${
            viewMode === "options"
              ? "bg-cyan-900/60 text-cyan-400 border border-cyan-700/60"
              : "text-slate-500 hover:text-slate-300 border border-slate-700/40"
          }`}
        >
          OPTIONS CHAIN
        </button>
      </div>

      {viewMode === "chart" && (
        <>
          {/* Main chart card */}
          <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg overflow-hidden">
            <SymbolTimeframeSelector
              symbol={symbol}
              timeframe={timeframe}
              onSymbol={setSymbol}
              onTimeframe={setTimeframe}
              onRefresh={handleRefresh}
              isLoading={isLoading || barsLoading || technicalLoading}
            />

            {/* Current signal summary bar */}
            {currentSignal && (
              <div className="px-4 py-2 bg-slate-950/40 border-b border-cyan-900/20 flex items-center gap-4 text-xs font-mono">
                <span className="text-slate-500">{symbol} SIGNAL:</span>
                <span
                  className="font-bold"
                  style={{
                    color:
                      currentSignal.signal === "ENTRY_NOW"
                        ? "#00ff88"
                        : currentSignal.signal === "NO_TRADE"
                        ? "#ff4466"
                        : "#ffcc00",
                  }}
                >
                  {currentSignal.signal}
                </span>
                {currentSignal.direction && currentSignal.direction !== "NEUTRAL" && (
                  <span
                    style={{
                      color: currentSignal.direction === "LONG" ? "#00ff88" : "#ff4466",
                    }}
                  >
                    {currentSignal.direction}
                  </span>
                )}
                {currentSignal.entry_price != null && (
                  <span className="text-slate-400">
                    Entry: <span className="text-white">{currentSignal.entry_price.toFixed(2)}</span>
                  </span>
                )}
                {currentSignal.stop_level != null && (
                  <span className="text-slate-400">
                    Stop: <span className="text-red-400">{currentSignal.stop_level.toFixed(2)}</span>
                  </span>
                )}
                {currentSignal.target_1 != null && (
                  <span className="text-slate-400">
                    T1: <span className="text-cyan-400">{currentSignal.target_1.toFixed(2)}</span>
                  </span>
                )}
                {technical?.regime && (
                  <span className="ml-auto text-slate-500">
                    Regime: <span className="text-white">{technical.regime}</span>
                  </span>
                )}
              </div>
            )}

            {/* Candlestick chart */}
            <div className="p-0 relative">
              {/* WebSocket live indicator */}
              <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5 text-[10px] font-mono text-slate-600">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    wsConnected ? "bg-green-500 animate-pulse" : "bg-slate-700"
                  }`}
                />
                {wsConnected
                  ? livePrice != null
                    ? livePrice.toFixed(2)
                    : "LIVE"
                  : "OFFLINE"}
              </div>
              <CandlestickChart bars={bars} technical={technical} height={440} livePrice={livePrice} />
            </div>

            {/* STC indicator panel */}
            <StcIndicatorPanel
              bars={bars}
              technical={technical}
              stcOb={technical?.adaptive_stc_ob ?? 83}
              stcOs={technical?.adaptive_stc_os ?? 15}
            />

            {/* Regime timeline */}
            <RegimeTimeline regime={regime} />
          </div>

          {/* Indicator snapshot cards row */}
          <div className="grid grid-cols-4 gap-3">
            {/* STC snapshot */}
            <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
              <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-1">STC</div>
              <div
                className="text-2xl font-mono font-bold"
                style={{
                  color:
                    technical?.stc_val == null
                      ? "#64748b"
                      : technical.stc_val >= (technical.adaptive_stc_ob ?? 83)
                      ? "#ff4466"
                      : technical.stc_val <= (technical.adaptive_stc_os ?? 15)
                      ? "#00ff88"
                      : "#00d4ff",
                }}
              >
                {technical?.stc_val?.toFixed(1) ?? "—"}
              </div>
              <div className="text-[10px] font-mono text-slate-600 mt-1">
                OS:{technical?.adaptive_stc_os ?? 15} OB:{technical?.adaptive_stc_ob ?? 83}
              </div>
            </div>

            {/* ATR */}
            <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
              <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-1">ATR</div>
              <div className="text-2xl font-mono font-bold text-white">
                {technical?.atr?.toFixed(2) ?? "—"}
              </div>
              <div className="text-[10px] font-mono text-slate-600 mt-1">14-period Wilder</div>
            </div>

            {/* EMA Trend */}
            <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
              <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-1">EMA TREND</div>
              <div
                className="text-lg font-mono font-bold"
                style={{
                  color:
                    technical?.ema_trend === "bullish"
                      ? "#00ff88"
                      : technical?.ema_trend === "bearish"
                      ? "#ff4466"
                      : "#64748b",
                }}
              >
                {technical?.ema_trend?.toUpperCase() ?? "—"}
              </div>
              <div className="text-[10px] font-mono text-slate-600 mt-1">
                8: {technical?.ema_8?.toFixed(2) ?? "—"}
              </div>
            </div>

            {/* Confidence */}
            <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
              <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-1">CONFIDENCE</div>
              <div
                className="text-2xl font-mono font-bold"
                style={{
                  color:
                    technical?.confidence == null
                      ? "#64748b"
                      : technical.confidence >= 0.7
                      ? "#00ff88"
                      : technical.confidence >= 0.5
                      ? "#ffcc00"
                      : "#ff4466",
                }}
              >
                {technical?.confidence != null
                  ? `${(technical.confidence * 100).toFixed(0)}%`
                  : "—"}
              </div>
              <div className="text-[10px] font-mono text-slate-600 mt-1">
                {technical?.signal ?? "signal pending"}
              </div>
            </div>
          </div>

          {/* Recent pipeline history */}
          {pipelineHistory.length > 0 && (
            <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-4">
              <div className="text-xs font-mono text-cyan-400 tracking-widest mb-3">
                RECENT PIPELINE DECISIONS
              </div>
              <div className="space-y-1">
                {pipelineHistory.slice(0, 5).map((entry, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs font-mono">
                    <span className="text-slate-600 w-16 shrink-0">
                      {entry.timestamp
                        ? new Date(entry.timestamp).toLocaleTimeString("en-US", {
                            hour: "2-digit",
                            minute: "2-digit",
                            hour12: false,
                          })
                        : "—"}
                    </span>
                    <span className="text-slate-400 w-10 shrink-0">{entry.symbol}</span>
                    <span
                      className="font-bold w-12 shrink-0"
                      style={{
                        color:
                          entry.final_action === "BUY"
                            ? "#00ff88"
                            : entry.final_action === "SELL"
                            ? "#ff4466"
                            : "#64748b",
                      }}
                    >
                      {entry.final_action}
                    </span>
                    {entry.confidence != null && (
                      <span className="text-slate-600">
                        {(entry.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    {entry.regime && (
                      <span className="text-slate-600">{entry.regime}</span>
                    )}
                    {entry.risk_verdict && (
                      <span
                        className="ml-auto"
                        style={{
                          color: entry.risk_verdict === "APPROVED" ? "#00ff88" : "#ff4466",
                        }}
                      >
                        {entry.risk_verdict}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {viewMode === "options" && (
        <OptionsChainPanel
          chain={chain}
          greeks={greeks}
          symbol={symbol}
          isLoading={chainLoading}
        />
      )}
    </div>
  );
}
