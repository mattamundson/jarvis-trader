"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import React from "react";
import useSWR from "swr";
import { fetchShadowMetrics, ShadowMetricsResponse } from "@/lib/api";
import { TrendingUp, Shield, Activity, BarChart3 } from "lucide-react";

export default function ShadowPerformanceWidget() {
  const { data, error, isLoading } = useSWR<ShadowMetricsResponse>(
    "/pipeline/shadow-metrics",
    () => fetchShadowMetrics(),
    { refreshInterval: POLL_INTERVAL.NORMAL }
  );

  if (isLoading) return <div className="animate-pulse bg-gray-800/50 rounded-xl h-48 w-full" />;
  if (error) return null;

  const metrics = data || { count: 0, total_pnl: 0, win_rate: 0, avg_win: 0, avg_loss: 0 };
  const isPositive = metrics.total_pnl >= 0;

  return (
    <div className="relative overflow-hidden bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl group transition-all hover:border-blue-500/50">
      {/* Background Glow */}
      <div className="absolute -top-24 -right-24 w-48 h-48 bg-blue-600/10 blur-[100px] rounded-full group-hover:bg-blue-600/20 transition-all" />
      
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <Shield className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h3 className="text-slate-100 font-bold tracking-tight">Shadow Mode</h3>
            <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">Experimental Performance</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-800/50 rounded-full border border-slate-700">
          <Activity className="w-3 h-3 text-emerald-400 animate-pulse" />
          <span className="text-[10px] font-bold text-slate-300 uppercase tracking-tighter">Live Monitor</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-1">
          <p className="text-slate-400 text-xs font-medium">Virtual P&L</p>
          <p className={`text-2xl font-mono font-bold ${isPositive ? "text-emerald-400" : "text-rose-400"}`}>
            {isPositive ? "+" : ""}${metrics.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-slate-400 text-xs font-medium">Win Rate</p>
          <div className="flex items-baseline gap-2">
            <p className="text-2xl font-mono font-bold text-slate-100">
              {(metrics.win_rate * 100).toFixed(1)}%
            </p>
            <TrendingUp className={`w-4 h-4 ${metrics.win_rate > 0.5 ? "text-emerald-400" : "text-slate-500"}`} />
          </div>
        </div>
      </div>

      <div className="mt-6 pt-6 border-t border-slate-800/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="text-center">
              <p className="text-[10px] text-slate-500 font-bold uppercase mb-1">Trades</p>
              <p className="text-sm font-mono text-slate-300">{metrics.count}</p>
            </div>
            <div className="h-8 w-px bg-slate-800" />
            <div className="text-center">
              <p className="text-[10px] text-slate-500 font-bold uppercase mb-1">Avg Win</p>
              <p className="text-sm font-mono text-emerald-400/80">${metrics.avg_win.toFixed(0)}</p>
            </div>
            <div className="h-8 w-px bg-slate-800" />
            <div className="text-center">
              <p className="text-[10px] text-slate-500 font-bold uppercase mb-1">Avg Loss</p>
              <p className="text-sm font-mono text-rose-400/80">${Math.abs(metrics.avg_loss).toFixed(0)}</p>
            </div>
          </div>
          <div className="p-2 bg-slate-800/50 rounded-lg cursor-help hover:bg-slate-700/50 transition-colors">
            <BarChart3 className="w-4 h-4 text-slate-400" />
          </div>
        </div>
      </div>
    </div>
  );
}
