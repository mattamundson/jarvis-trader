"use client";

import React from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { TrendingUp, TrendingDown, Shield, Zap, BarChart2 } from "lucide-react";

interface StrategyCSignal {
  generated_at: string;
  strategy: string;
  effective_date: string;
  execution_note: string;
  holdings: Record<string, number>;
  combined_scale: number;
  pre_mtf_scale: number;
  layers: {
    momentum_signal: {
      risk_regime: string;
      absolute_mom_pass: boolean;
    };
    vol_targeting: {
      realized_vol_pct: number;
      vol_target_pct: number;
      vol_regime: string;
    };
    vix_composite: {
      vix: number;
      vix_regime: string;
    };
    mtf_signal: {
      mtf_scale: number;
      weekly_momentum: string;
      monthly_momentum: string;
      daily_confirmation: string;
      breadth: string;
      votes_bull: number;
      confidence: string;
    };
  };
}

function pct(n: number) {
  return (n * 100).toFixed(1) + "%";
}

function MomentumBadge({ val }: { val: string }) {
  const bull = val === "BULL";
  return (
    <span
      className="text-[9px] font-bold px-1 rounded"
      style={{
        color: bull ? "#00ff88" : "#ff4444",
        background: bull ? "rgba(0,255,136,0.1)" : "rgba(255,68,68,0.1)",
      }}
    >
      {val}
    </span>
  );
}

export function StrategyCPlusCard() {
  const { data, error, isLoading } = useSWR<StrategyCSignal>(
    "/v1/strategy_c/signal",
    () => fetchEngine<StrategyCSignal>("/v1/strategy_c/signal"),
    { refreshInterval: 300_000, shouldRetryOnError: false }
  );

  const regime = data?.layers?.momentum_signal?.risk_regime ?? "—";
  const scale = data?.combined_scale ?? 0;
  const preScale = data?.pre_mtf_scale ?? scale;
  const holdings = data?.holdings ?? {};
  const mtf = data?.layers?.mtf_signal;
  const vix = data?.layers?.vix_composite;
  const vol = data?.layers?.vol_targeting;
  const effectiveDate = data?.effective_date;

  const isRiskOn = regime === "RISK_ON";
  const regimeColor = isRiskOn ? "#00d4ff" : "#ff4444";

  const holdingsList = Object.entries(holdings)
    .sort((a, b) => b[1] - a[1])
    .map(([sym, w]) => ({ sym, w }));

  return (
    <div
      className="rounded border p-3 text-xs font-mono"
      style={{ background: "#0d1117", borderColor: isRiskOn ? "#1e3a5f" : "#2d1b1b" }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <BarChart2 className="w-3 h-3" style={{ color: regimeColor }} />
        <span
          className="font-bold tracking-widest text-[10px]"
          style={{ color: regimeColor }}
        >
          STRATEGY C+
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded border font-bold ml-1"
          style={{
            color: regimeColor,
            borderColor: isRiskOn ? "#1e3a5f" : "#3d1a1a",
            background: isRiskOn ? "#0a1929" : "#1a0a0a",
          }}
        >
          {isLoading ? "..." : regime.replace("_", " ")}
        </span>
        {effectiveDate && (
          <span className="ml-auto text-[10px] text-slate-600">{effectiveDate}</span>
        )}
      </div>

      {error && !isLoading && (
        <div className="text-[10px] text-slate-600 mb-2">
          Engine offline — showing cached signal from last run
        </div>
      )}

      {/* Scale bar */}
      <div className="mb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-slate-500">ALLOCATION SCALE</span>
          <span style={{ color: regimeColor }} className="font-bold">
            {pct(scale)}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(scale * 100, 100)}%`,
              background: `linear-gradient(90deg, ${regimeColor}88, ${regimeColor})`,
            }}
          />
        </div>
        {mtf && (
          <div className="text-[10px] text-slate-600 mt-0.5">
            {pct(preScale)} → MTF ×{mtf.mtf_scale.toFixed(2)} → {pct(scale)}
          </div>
        )}
      </div>

      {/* Holdings */}
      {holdingsList.length > 0 && (
        <div className="mb-3">
          <div className="text-[10px] text-slate-500 mb-1.5">HOLDINGS</div>
          <div className="flex flex-wrap gap-1.5">
            {holdingsList.map(({ sym, w }) => (
              <div
                key={sym}
                className="flex flex-col items-center rounded px-2 py-1"
                style={{ background: "#070d14", border: "1px solid #1e293b" }}
              >
                <span className="text-[10px] font-bold" style={{ color: regimeColor }}>{sym}</span>
                <span className="text-white text-[11px]">{pct(w)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MTF signals */}
      {mtf && (
        <div className="mb-2">
          <div className="text-[10px] text-slate-500 mb-1.5">
            MTF · {mtf.votes_bull}/3 BULL · CONF: {mtf.confidence}
          </div>
          <div className="flex gap-2">
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-slate-600">W</span>
              <MomentumBadge val={mtf.weekly_momentum} />
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-slate-600">M</span>
              <MomentumBadge val={mtf.monthly_momentum} />
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-slate-600">D</span>
              <MomentumBadge val={mtf.daily_confirmation} />
            </div>
            <span className="ml-auto text-[10px]" style={{ color: mtf.breadth === "EXPANDING" ? "#00d4ff" : "#ff8800" }}>
              {mtf.breadth}
            </span>
          </div>
        </div>
      )}

      {/* VIX + Vol */}
      {(vix || vol) && (
        <div
          className="flex gap-3 text-[10px] pt-2 border-t"
          style={{ borderColor: "#1e293b" }}
        >
          {vix && (
            <span>
              <span className="text-slate-500">VIX </span>
              <span className="text-white">{vix.vix.toFixed(2)}</span>
              <span className="text-slate-600"> ({vix.vix_regime})</span>
            </span>
          )}
          {vol && (
            <span>
              <span className="text-slate-500">RealVol </span>
              <span className="text-amber-400">{vol.realized_vol_pct.toFixed(1)}%</span>
              <span className="text-slate-600"> · {vol.vol_regime}</span>
            </span>
          )}
        </div>
      )}

      {/* Execute note */}
      {data?.execution_note && (
        <div className="text-[10px] text-slate-600 mt-1.5">{data.execution_note}</div>
      )}
    </div>
  );
}
