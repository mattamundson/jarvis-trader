"use client";
import { useState } from "react";
import type { OptionsChainData, OptionsGreeksPortfolio, OptionsContract } from "@/lib/api";

interface OptionsChainPanelProps {
  chain?: OptionsChainData | null;
  greeks?: OptionsGreeksPortfolio | null;
  symbol: string;
  isLoading?: boolean;
}

function fmt(n?: number, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
}

function deltaColor(delta?: number): string {
  if (delta == null) return "#64748b";
  const abs = Math.abs(delta);
  if (abs >= 0.6) return "#00ff88";
  if (abs >= 0.3) return "#ffcc00";
  return "#64748b";
}

export function OptionsChainPanel({ chain, greeks, symbol, isLoading }: OptionsChainPanelProps) {
  const [deltaFilter, setDeltaFilter] = useState<"all" | "near-atm" | "otm">("near-atm");

  if (isLoading) {
    return (
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-8 text-center">
        <div className="text-slate-500 font-mono text-sm">Loading options chain for {symbol}...</div>
      </div>
    );
  }

  if (!chain || chain.error) {
    return (
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-8 text-center space-y-2">
        <div className="text-slate-400 font-mono text-sm">
          Options chain unavailable for {symbol}
        </div>
        <div className="text-slate-600 font-mono text-xs">
          {chain?.error || "Engine may be offline or options engine not yet active"}
        </div>
        <div className="text-slate-600 font-mono text-xs mt-4">
          Options infrastructure: engine/options/ (6 files) — awaiting activation
        </div>
        <div className="grid grid-cols-3 gap-3 mt-4 text-left">
          {["greeks_monitor.py", "strategy_executor.py", "chain_fetcher.py", "premium_calculator.py", "position_manager.py", "7 strategies built"].map((item) => (
            <div key={item} className="flex items-center gap-2 text-xs font-mono">
              <span className="text-green-500">✓</span>
              <span className="text-slate-500">{item}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const underlying = chain.underlying_price;

  // Filter contracts based on delta filter
  const filterContracts = (contracts: OptionsContract[], type: "call" | "put") => {
    const sorted = [...contracts].sort((a, b) => a.strike - b.strike);
    if (deltaFilter === "all") return sorted;
    if (deltaFilter === "near-atm") {
      // strikes within 5% of underlying
      return sorted.filter((c) => Math.abs(c.strike - underlying) / underlying < 0.05);
    }
    if (deltaFilter === "otm") {
      return sorted.filter((c) =>
        type === "call" ? c.strike >= underlying : c.strike <= underlying
      );
    }
    return sorted;
  };

  const calls = filterContracts(chain.calls, "call");
  const puts = filterContracts(chain.puts, "put");

  // Find ATM strike
  const atmStrike = calls.reduce((prev, curr) =>
    Math.abs(curr.strike - underlying) < Math.abs(prev.strike - underlying) ? curr : prev,
    calls[0]
  )?.strike;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3 flex items-center gap-4">
        <div>
          <span className="text-xs font-mono text-slate-500">OPTIONS CHAIN — </span>
          <span className="text-sm font-mono font-bold text-cyan-400">{symbol}</span>
        </div>
        <div className="text-xs font-mono text-slate-500">
          Expiry: <span className="text-white">{chain.expiry}</span>
        </div>
        <div className="text-xs font-mono text-slate-500">
          Underlying: <span className="text-white">${underlying.toFixed(2)}</span>
        </div>
        {chain.iv_rank != null && (
          <div className="text-xs font-mono text-slate-500">
            IV Rank:{" "}
            <span
              className="font-bold"
              style={{
                color: chain.iv_rank >= 50 ? "#00ff88" : chain.iv_rank >= 30 ? "#ffcc00" : "#64748b",
              }}
            >
              {chain.iv_rank.toFixed(0)}%
            </span>
          </div>
        )}

        {/* Delta filter */}
        <div className="ml-auto flex gap-1">
          {(["near-atm", "otm", "all"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setDeltaFilter(f)}
              className={`px-2 py-0.5 text-[10px] font-mono rounded ${
                deltaFilter === f
                  ? "bg-cyan-900/60 text-cyan-400 border border-cyan-700/60"
                  : "text-slate-500 border border-slate-700/40"
              }`}
            >
              {f.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Portfolio Greeks */}
      {greeks && !greeks.error && (
        <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
          <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-2">PORTFOLIO GREEKS</div>
          <div className="grid grid-cols-5 gap-4 text-center">
            {[
              { label: "Δ Delta", value: greeks.total_delta, color: "#00d4ff" },
              { label: "Γ Gamma", value: greeks.total_gamma, color: "#7c3aed" },
              { label: "Θ Theta", value: greeks.total_theta, color: "#ff4466" },
              { label: "ν Vega", value: greeks.total_vega, color: "#00ff88" },
              { label: "Positions", value: greeks.positions_count, color: "#ffcc00" },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div className="text-[10px] font-mono text-slate-500">{label}</div>
                <div className="text-sm font-mono font-bold" style={{ color }}>
                  {typeof value === "number" ? value.toFixed(2) : value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Options table */}
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_auto_1fr] text-[10px] font-mono text-slate-500 bg-slate-950/60 border-b border-cyan-900/30">
          <div className="grid grid-cols-5 gap-2 px-4 py-2 text-right">
            <span>DELTA</span><span>BID</span><span>ASK</span><span>IV</span><span>OI</span>
          </div>
          <div className="px-6 py-2 text-center font-bold text-cyan-400">CALLS ← STRIKE → PUTS</div>
          <div className="grid grid-cols-5 gap-2 px-4 py-2 text-left">
            <span>DELTA</span><span>BID</span><span>ASK</span><span>IV</span><span>OI</span>
          </div>
        </div>

        {/* Rows — pair calls and puts by strike */}
        <div className="divide-y divide-slate-800/40 max-h-80 overflow-y-auto">
          {calls.slice(0, 12).map((call, i) => {
            const put = puts[i];
            const isAtm = call.strike === atmStrike;
            return (
              <div
                key={call.strike}
                className={`grid grid-cols-[1fr_auto_1fr] text-xs font-mono ${
                  isAtm ? "bg-cyan-900/10 border-l-2 border-cyan-500" : ""
                }`}
              >
                {/* Call side */}
                <div className="grid grid-cols-5 gap-2 px-4 py-1.5 text-right">
                  <span style={{ color: deltaColor(call.delta) }}>{fmt(call.delta, 2)}</span>
                  <span className="text-green-400">{fmt(call.bid)}</span>
                  <span className="text-green-400">{fmt(call.ask)}</span>
                  <span className="text-slate-400">{call.iv != null ? `${(call.iv * 100).toFixed(0)}%` : "—"}</span>
                  <span className="text-slate-500">{call.open_interest ?? "—"}</span>
                </div>

                {/* Strike */}
                <div className={`px-4 py-1.5 text-center font-bold ${isAtm ? "text-cyan-400" : "text-slate-400"}`}>
                  {call.strike.toFixed(call.strike < 10 ? 2 : 0)}
                  {isAtm && <span className="ml-1 text-[9px] text-cyan-600">ATM</span>}
                </div>

                {/* Put side */}
                {put ? (
                  <div className="grid grid-cols-5 gap-2 px-4 py-1.5 text-left">
                    <span style={{ color: deltaColor(put.delta) }}>{fmt(Math.abs(put.delta ?? 0), 2)}</span>
                    <span className="text-red-400">{fmt(put.bid)}</span>
                    <span className="text-red-400">{fmt(put.ask)}</span>
                    <span className="text-slate-400">{put.iv != null ? `${(put.iv * 100).toFixed(0)}%` : "—"}</span>
                    <span className="text-slate-500">{put.open_interest ?? "—"}</span>
                  </div>
                ) : (
                  <div className="px-4 py-1.5 text-slate-700">—</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Strategy quick-reference */}
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-3">
        <div className="text-[10px] font-mono text-slate-500 tracking-widest mb-2">7 AVAILABLE STRATEGIES</div>
        <div className="grid grid-cols-4 gap-2">
          {[
            { name: "Covered Call", regime: "TRENDING", vix: "NORMAL/ELEVATED" },
            { name: "Credit Spread", regime: "ANY", vix: "HIGH IV RANK >30%" },
            { name: "Iron Condor", regime: "RANGING", vix: "NORMAL/ELEVATED" },
            { name: "Protective Put", regime: "VOLATILE", vix: "ELEVATED/HIGH" },
            { name: "Straddle", regime: "PRE-EVENT", vix: "FOMC/CPI" },
            { name: "Strangle", regime: "PRE-EVENT", vix: "FOMC/CPI" },
            { name: "Ratio Spread", regime: "TRENDING", vix: "ANY" },
          ].map(({ name, regime, vix }) => (
            <div key={name} className="text-[9px] font-mono p-2 bg-slate-950/60 rounded border border-slate-700/40">
              <div className="text-cyan-400 font-bold">{name}</div>
              <div className="text-slate-600">{regime}</div>
              <div className="text-slate-700">{vix}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
