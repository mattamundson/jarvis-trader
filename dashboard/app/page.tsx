"use client";

import { useEffect, useState, useMemo } from "react";
import useSWR from "swr";
import Link from "next/link";
import dynamic from "next/dynamic";
import { JetBrains_Mono } from "next/font/google";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, TrendingUp, TrendingDown, Activity } from "lucide-react";
import type { FlowSnapshot } from "@/lib/flowTypes";
import { isStale, biasLabel, analyzeGateAction, volumePaceRatio } from "@/lib/flowTypes";
import { fetchDashboardApi } from "@/lib/api";

const fontMono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "600", "700"] });

const CvdChart = dynamic(
  () => import("@/components/flow/CvdChart").then((m) => ({ default: m.CvdChart })),
  { ssr: false, loading: () => <div className="h-80 animate-pulse rounded bg-slate-950/40" /> }
);

async function fetchFlow(): Promise<FlowSnapshot> {
  return fetchDashboardApi<FlowSnapshot>("/api/flow");
}

export default function Home() {
  const { data: flow, error } = useSWR<FlowSnapshot>("flow", fetchFlow, {
    refreshInterval: 5000,
    shouldRetryOnError: false,
  });

  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const stale = flow && isStale(flow.ts);
  const bias = flow ? biasLabel(flow.es.last, flow.es.vwap) : "NEUTRAL";

  const gateAnalyses = useMemo(() => {
    if (!flow) return [];
    return flow.gates.map((gate) =>
      analyzeGateAction(gate, flow.es.last, flow.es.cvd, flow.es.cvdLow, flow.es.deltaAtPrice)
    );
  }, [flow]);

  const volPace = useMemo(() => {
    if (!flow || flow.es.bars1m.length === 0) return null;
    return volumePaceRatio(flow.es.bars1m);
  }, [flow]);

  return (
    <div className={`min-h-screen bg-gray-950 text-gray-100 p-4 ${fontMono.className}`}>
      <div className="flex items-center justify-between mb-4 border-b border-cyan-900/40 pb-3">
        <h1 className="text-xl font-bold text-cyan-400 tracking-widest uppercase" data-testid="flow-page-header">
          JARVIS TRADER — ES ORDER FLOW
        </h1>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 font-mono">
            {now ? now.toLocaleTimeString("en-US", { hour12: false }) : "--:--:--"}
          </span>
          <Badge variant="warn" className="font-mono text-xs">
            PAPER RESEARCH TOOL
          </Badge>
          {stale && (
            <Badge variant="bear" className="font-mono text-xs animate-pulse">
              STALE DATA
            </Badge>
          )}
        </div>
      </div>

      {!flow && (
        <div className="flex items-center justify-center py-20">
          <div className="text-slate-500 font-mono animate-pulse">Loading flow data...</div>
        </div>
      )}

      {flow && (
        <>
          <div className="mb-4 p-3 bg-slate-900/60 border border-cyan-900/50 rounded">
            <div className="flex items-center justify-between text-sm font-mono">
              <div className="flex items-center gap-4">
                <div>
                  <span className="text-slate-500">ES:</span>{" "}
                  <span className="text-white font-bold text-lg">{flow.es.last.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-slate-500">VWAP:</span>{" "}
                  <span className="text-cyan-400">{flow.es.vwap.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-slate-500">ON H/L:</span>{" "}
                  <span className="text-slate-300">
                    {flow.es.onHigh.toFixed(2)} / {flow.es.onLow.toFixed(2)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Bias:</span>{" "}
                  <Badge
                    variant={bias === "BULL" ? "bull" : bias === "BEAR" ? "bear" : "neutral"}
                    className="ml-1"
                  >
                    {bias}
                  </Badge>
                </div>
              </div>
              <Badge variant="bear" className="font-mono text-xs">
                Live legal? NO, size 0
              </Badge>
            </div>
          </div>

          <div className="grid grid-cols-12 gap-4 mb-4">
            <div className="col-span-8">
              <Card className="bg-slate-900/60 border border-cyan-900/50 h-full">
                <CardHeader className="pb-2 pt-3 px-4">
                  <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
                    <Activity className="w-3 h-3" />
                    ORDER FLOW PANEL
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-4 pb-3">
                  <div className="space-y-4">
                    <div>
                      <div className="text-xs text-slate-500 mb-2">
                        CVD: {flow.es.cvd} (low: {flow.es.cvdLow}) | 1m Price + CVD Line
                      </div>
                      <div className="bg-slate-950/60 border border-slate-800 rounded p-2">
                        <CvdChart
                          bars={flow.es.bars1m}
                          gates={flow.gates}
                          cvdLow={flow.es.cvdLow}
                          currentCvd={flow.es.cvd}
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <div className="text-xs text-slate-500 mb-2">Delta-at-Price Ladder</div>
                        <div className="bg-slate-950/60 border border-slate-800 rounded p-2 space-y-1">
                          {flow.es.deltaAtPrice.map((d) => {
                            const netDelta = d.bidLots - d.askLots;
                            const maxLots = Math.max(d.bidLots, d.askLots);
                            const bidWidth = (d.bidLots / maxLots) * 100;
                            const askWidth = (d.askLots / maxLots) * 100;
                            return (
                              <div key={d.price} className="flex items-center gap-2 text-xs">
                                <div className="w-16 text-right text-slate-400">
                                  {d.price.toFixed(2)}
                                </div>
                                <div className="flex-1 flex items-center gap-1">
                                  <div
                                    className="bg-green-500/30 h-4 text-right pr-1 text-green-300 text-[10px] leading-4"
                                    style={{ width: `${bidWidth}%` }}
                                  >
                                    {d.bidLots}
                                  </div>
                                  <div
                                    className="bg-red-500/30 h-4 pl-1 text-red-300 text-[10px] leading-4"
                                    style={{ width: `${askWidth}%` }}
                                  >
                                    {d.askLots}
                                  </div>
                                </div>
                                <div
                                  className={`w-12 text-right font-bold ${
                                    netDelta > 0
                                      ? "text-green-400"
                                      : netDelta < 0
                                        ? "text-red-400"
                                        : "text-slate-500"
                                  }`}
                                >
                                  {netDelta > 0 ? "+" : ""}
                                  {netDelta}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      <div>
                        <div className="text-xs text-slate-500 mb-2">Big Print Tape (≥20 lots)</div>
                        <div className="bg-slate-950/60 border border-slate-800 rounded p-2 space-y-1 max-h-32 overflow-y-auto">
                          {flow.es.bigPrints.length === 0 ? (
                            <div className="text-xs text-slate-600 py-8 text-center">
                              No big prints
                            </div>
                          ) : (
                            flow.es.bigPrints.map((bp, i) => (
                              <div
                                key={i}
                                className="flex items-center justify-between text-xs border-b border-slate-800/50 pb-1 last:border-0"
                              >
                                <span className="text-slate-500">
                                  {new Date(bp.ts).toLocaleTimeString("en-US", {
                                    hour12: false,
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    second: "2-digit",
                                  })}
                                </span>
                                <span className="text-white font-bold">{bp.price.toFixed(2)}</span>
                                <span
                                  className={`font-bold ${bp.side === "bid" ? "text-green-400" : "text-red-400"}`}
                                >
                                  {bp.lots} {bp.side}
                                </span>
                              </div>
                            ))
                          )}
                        </div>
                        <div className="mt-2 space-y-1">
                          <div className="text-xs text-slate-500 mb-1">Gate Actions</div>
                          {gateAnalyses.map((ga, i) => (
                            <div
                              key={i}
                              className="flex items-center justify-between text-xs py-0.5"
                            >
                              <span className="text-slate-400">{ga.level.toFixed(0)}</span>
                              <Badge
                                variant={
                                  ga.action === "BREAK"
                                    ? "bear"
                                    : ga.action === "ABSORB"
                                      ? "bull"
                                      : "neutral"
                                }
                                className="text-[10px] py-0"
                              >
                                {ga.action}
                              </Badge>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="col-span-4">
              <Card className="bg-slate-900/60 border border-cyan-900/50 h-full">
                <CardHeader className="pb-2 pt-3 px-4">
                  <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
                    <TrendingUp className="w-3 h-3" />
                    GATE LADDER & GEX
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-4 pb-3">
                  <div className="space-y-3">
                    <div>
                      <div className="text-xs text-slate-500 mb-2">Gate Levels</div>
                      <div className="space-y-1">
                        {flow.gates.map((g, i) => {
                          const analysis = gateAnalyses[i];
                          return (
                            <div
                              key={i}
                              className="flex items-center justify-between text-xs py-1 border-b border-slate-800/50 last:border-0"
                            >
                              <span className="text-white font-bold">{g.level.toFixed(2)}</span>
                              <div className="flex items-center gap-1">
                                <Badge
                                  variant={
                                    g.status === "untested"
                                      ? "neutral"
                                      : g.status === "testing"
                                        ? "warn"
                                        : "bear"
                                  }
                                  className="text-[10px] py-0"
                                >
                                  {g.status.toUpperCase()}
                                </Badge>
                                {analysis && analysis.action !== "NEUTRAL" && (
                                  <Badge
                                    variant={analysis.action === "ABSORB" ? "bull" : "bear"}
                                    className="text-[10px] py-0"
                                  >
                                    {analysis.action}
                                  </Badge>
                                )}
                              </div>
                              <span className="text-slate-500">{g.closeCount}/2</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-xs text-slate-500">GEX Levels</div>
                        <Badge variant="warn" className="text-[10px]">
                          DELAYED
                        </Badge>
                      </div>
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">Call Wall:</span>
                          <span className="text-green-400 font-bold">
                            {flow.gex.callWall.toFixed(0)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Put Wall:</span>
                          <span className="text-red-400 font-bold">
                            {flow.gex.putWall.toFixed(0)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Flip:</span>
                          <span className="text-cyan-400 font-bold">
                            {flow.gex.flip.toFixed(0)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Pin:</span>
                          <span className="text-yellow-400 font-bold">
                            {flow.gex.pin.toFixed(0)}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-600 mt-1">
                          As of:{" "}
                          {new Date(flow.gex.asOf).toLocaleTimeString("en-US", {
                            hour12: false,
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>

          <div className="grid grid-cols-4 gap-4">
            <Card className="bg-slate-900/60 border border-cyan-900/50">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
                  NQ CROSS-CHECK
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500">NQ Last:</span>
                    <span className="text-white font-bold">{flow.nq.last.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">NQ VWAP:</span>
                    <span className="text-cyan-400">{flow.nq.vwap.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">NQ vs VWAP:</span>
                    <Badge
                      variant={
                        flow.nq.last > flow.nq.vwap
                          ? "bull"
                          : flow.nq.last < flow.nq.vwap
                            ? "bear"
                            : "neutral"
                      }
                    >
                      {flow.nq.last > flow.nq.vwap ? "ABOVE" : flow.nq.last < flow.nq.vwap ? "BELOW" : "AT"}
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/60 border border-cyan-900/50">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
                  VOLUME PACE
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                {volPace ? (
                  <div className="space-y-2">
                    <div className="flex items-baseline justify-between">
                      <span className="text-xs text-slate-500">Current vs Avg</span>
                      <span className={`text-2xl font-bold font-mono ${volPace.color}`}>
                        {volPace.ratio.toFixed(2)}x
                      </span>
                    </div>
                    <div className="text-xs text-slate-600">
                      {volPace.ratio >= 1.5
                        ? "Heavy volume"
                        : volPace.ratio >= 1.2
                          ? "Above average"
                          : volPace.ratio <= 0.7
                            ? "Light volume"
                            : volPace.ratio <= 0.85
                              ? "Below average"
                              : "Normal pace"}
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-slate-600 py-8 text-center">
                    Insufficient data
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="bg-slate-900/60 border border-cyan-900/50 col-span-2">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
                  SETUP SCORECARD
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                <Link
                  href="/setup-scorecard"
                  className="block text-center py-6 hover:bg-cyan-950/20 rounded transition-colors"
                >
                  <div className="text-sm text-cyan-400 font-bold mb-1">
                    View Full Setup Scorecard →
                  </div>
                  <div className="text-xs text-slate-500">
                    Legacy system archive & validation status
                  </div>
                </Link>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
