"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DataFreshness } from "@/components/DataFreshness";
import { fetchDashboardApi } from "@/lib/api";
import type { FlowSnapshot } from "@/lib/flowTypes";
import {
  aggregateBarsTo5m,
  buildFootprintBar,
  buildCompositeProfile,
  type FootprintBar,
  type CompositeProfile,
} from "@/lib/footprint";

async function fetchFlow(): Promise<FlowSnapshot> {
  return fetchDashboardApi<FlowSnapshot>("/api/flow");
}

export default function FootprintPage() {
  const { data: flow } = useSWR<FlowSnapshot>("flow", fetchFlow, {
    refreshInterval: 5000,
    shouldRetryOnError: false,
  });

  const bars5m = useMemo(() => {
    if (!flow) return [];
    return aggregateBarsTo5m(flow.es.bars1m);
  }, [flow]);

  const footprintBars = useMemo((): FootprintBar[] => {
    return bars5m.map(buildFootprintBar);
  }, [bars5m]);

  const compositeProfile = useMemo((): CompositeProfile | null => {
    if (bars5m.length === 0) return null;
    return buildCompositeProfile(bars5m);
  }, [bars5m]);

  const hasFootprintData = useMemo(() => {
    return bars5m.some((bar) => bar.bidAtPrice || bar.askAtPrice);
  }, [bars5m]);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-4 font-mono">
      <div className="flex items-center justify-between mb-4 border-b border-cyan-900/40 pb-3">
        <h1 className="text-xl font-bold text-cyan-400 tracking-widest uppercase">
          FOOTPRINT & VOLUME PROFILE
        </h1>
        <div className="flex items-center gap-3">
          {flow && (
            <DataFreshness
              source="Order Flow"
              dataTimestamp={flow.ts}
              isFixture={flow.fixture}
              stalenessThresholdMs={120_000}
            />
          )}
        </div>
      </div>

      {!flow && (
        <div className="flex items-center justify-center py-20">
          <div className="text-slate-500 font-mono animate-pulse">Loading flow data...</div>
        </div>
      )}

      {flow && !hasFootprintData && (
        <Card className="bg-slate-900/60 border border-yellow-900/50">
          <CardContent className="p-6">
            <div className="text-center space-y-3">
              <Badge variant="warn" className="text-sm">
                INCOMPLETE DATA
              </Badge>
              <p className="text-slate-300">
                The live flow snapshot does not include per-bar bid/ask-at-price data.
              </p>
              <div className="text-xs text-slate-500 space-y-1 text-left bg-slate-950/60 p-3 rounded border border-slate-800">
                <p className="font-bold text-slate-400 mb-2">
                  Required: AmoSZN pusher must extend the flow snapshot schema
                </p>
                <p>
                  Each bar in <code>bars1m[]</code> needs optional fields:
                </p>
                <pre className="text-slate-400 mt-2 pl-4">
                  {`bidAtPrice?: { [price: string]: number }
askAtPrice?: { [price: string]: number }`}
                </pre>
                <p className="mt-2">
                  Example: <code>{`{ "7718.25": 15, "7718.50": 8 }`}</code> means 15 lots traded
                  at bid at 7718.25, 8 lots at 7718.50.
                </p>
                <p className="mt-2">
                  Once populated, this page will render the 5m footprint and composite volume
                  profile.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {flow && hasFootprintData && (
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-8">
            <Card className="bg-slate-900/60 border border-cyan-900/50">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
                  5-MINUTE FOOTPRINT CHART
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                <div className="space-y-3">
                  {footprintBars.length === 0 && (
                    <div className="text-xs text-slate-600 py-8 text-center">
                      No footprint data available
                    </div>
                  )}
                  {footprintBars.map((bar, i) => (
                    <div
                      key={i}
                      className="border border-slate-800 rounded p-2 bg-slate-950/40"
                    >
                      <div className="flex items-center justify-between mb-2 text-xs text-slate-500">
                        <span>
                          {new Date(bar.ts).toLocaleTimeString("en-US", {
                            hour12: false,
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                        <span>
                          O: {bar.open.toFixed(2)} H: {bar.high.toFixed(2)} L:{" "}
                          {bar.low.toFixed(2)} C: {bar.close.toFixed(2)}
                        </span>
                        <span>Vol: {bar.totalVolume}</span>
                        <Badge variant={bar.netDelta >= 0 ? "bull" : "bear"} className="text-xs">
                          Δ {bar.netDelta > 0 ? "+" : ""}
                          {bar.netDelta}
                        </Badge>
                      </div>
                      <div className="space-y-0.5">
                        {bar.levels.map((level, j) => {
                          const maxVol = Math.max(
                            ...bar.levels.map((l) => Math.max(l.bidLots, l.askLots))
                          );
                          const bidWidth = (level.bidLots / maxVol) * 100;
                          const askWidth = (level.askLots / maxVol) * 100;

                          return (
                            <div key={j} className="flex items-center gap-2 text-xs">
                              <div className="w-16 text-right text-slate-400">
                                {level.price.toFixed(2)}
                              </div>
                              <div className="flex-1 flex items-center gap-1">
                                <div
                                  className="bg-green-500/30 h-3 text-right pr-1 text-green-300 text-[10px] leading-3 overflow-hidden"
                                  style={{ width: `${bidWidth}%` }}
                                >
                                  {level.bidLots > 0 && level.bidLots}
                                </div>
                                <div
                                  className="bg-red-500/30 h-3 pl-1 text-red-300 text-[10px] leading-3 overflow-hidden"
                                  style={{ width: `${askWidth}%` }}
                                >
                                  {level.askLots > 0 && level.askLots}
                                </div>
                              </div>
                              <div
                                className={`w-12 text-right font-bold ${
                                  level.delta > 0
                                    ? "text-green-400"
                                    : level.delta < 0
                                      ? "text-red-400"
                                      : "text-slate-500"
                                }`}
                              >
                                {level.delta > 0 ? "+" : ""}
                                {level.delta}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="col-span-4">
            <Card className="bg-slate-900/60 border border-cyan-900/50">
              <CardHeader className="pb-2 pt-3 px-4">
                <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
                  COMPOSITE VOLUME PROFILE
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-3">
                {!compositeProfile && (
                  <div className="text-xs text-slate-600 py-8 text-center">
                    No profile data available
                  </div>
                )}
                {compositeProfile && (
                  <div className="space-y-3">
                    <div className="text-xs text-slate-500 space-y-1">
                      <div className="flex justify-between">
                        <span>POC:</span>
                        <span className="text-cyan-400 font-bold">
                          {compositeProfile.poc.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>VAH:</span>
                        <span className="text-green-400 font-bold">
                          {compositeProfile.valueAreaHigh.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>VAL:</span>
                        <span className="text-red-400 font-bold">
                          {compositeProfile.valueAreaLow.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Total Vol:</span>
                        <span className="text-slate-300 font-bold">
                          {compositeProfile.totalVolume}
                        </span>
                      </div>
                    </div>

                    <div className="border-t border-slate-800 pt-3 space-y-0.5">
                      {compositeProfile.levels.map((level, i) => {
                        const maxVol = Math.max(...compositeProfile.levels.map((l) => l.volume));
                        const width = (level.volume / maxVol) * 100;
                        const isPOC = Math.abs(level.price - compositeProfile.poc) < 0.5;
                        const inVA =
                          level.price >= compositeProfile.valueAreaLow &&
                          level.price <= compositeProfile.valueAreaHigh;

                        return (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <div
                              className={`w-16 text-right ${
                                isPOC
                                  ? "text-cyan-400 font-bold"
                                  : inVA
                                    ? "text-slate-300"
                                    : "text-slate-500"
                              }`}
                            >
                              {level.price.toFixed(2)}
                            </div>
                            <div className="flex-1">
                              <div
                                className={`h-3 ${
                                  isPOC
                                    ? "bg-cyan-500/50"
                                    : inVA
                                      ? "bg-slate-600/50"
                                      : "bg-slate-700/30"
                                }`}
                                style={{ width: `${width}%` }}
                              />
                            </div>
                            <div className="w-12 text-right text-slate-500">{level.volume}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
