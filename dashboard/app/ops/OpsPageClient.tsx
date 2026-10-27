"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { AlertTriangle, CheckCircle2, Clock, XCircle, Shield } from "lucide-react";
import { fetchDashboardApi } from "@/lib/api";
import type { OpsFeedData } from "@/lib/opsTypes";
import {
  calculateProofBarProgress,
  formatTimestamp,
  calculateAgeSeconds,
  formatDuration,
} from "@/lib/opsHelpers";
import { Badge } from "@/components/ui/badge";

function fetcher<T>(url: string): Promise<T> {
  return fetchDashboardApi<T>(url);
}

export default function OpsPageClient() {
  const { data, error, isLoading } = useSWR<OpsFeedData>("/api/ops", fetcher, {
    refreshInterval: 30_000,
  });

  const [currentTime, setCurrentTime] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const proofBarProgress = data
    ? calculateProofBarProgress(data.proof_bar.clean_paper_sessions, data.proof_bar.scored_setups)
    : 0;

  const dataAge = data?.timestamp ? calculateAgeSeconds(data.timestamp) : -1;

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-[#e0e0e0] font-mono">
      {/* Header */}
      <header className="border-b border-[#1a1a1a] bg-[#0d0d0d] px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-[#00ff00]">JARVIS OPS TERMINAL</h1>
            <p className="text-xs text-[#808080] mt-1">Paper Trading Operations Dashboard</p>
          </div>
          {data?.timestamp && (
            <div className="text-right">
              <p className="text-xs text-[#808080]">Data pulled</p>
              <p className="text-sm text-[#e0e0e0]">{formatTimestamp(data.timestamp)}</p>
              <p className="text-xs text-[#606060]">{formatDuration(dataAge)} ago</p>
            </div>
          )}
        </div>
      </header>

      <main className="px-6 py-6 space-y-6 max-w-[1800px] mx-auto">
        {/* Loading state */}
        {isLoading && !data && (
          <div className="text-center py-12">
            <div className="inline-block animate-pulse text-[#00ff00]">Loading ops data...</div>
          </div>
        )}

        {/* Error state */}
        {error && !data && (
          <div className="border border-[#ff0000] bg-[#1a0000] rounded p-4 text-center">
            <XCircle className="h-8 w-8 text-[#ff0000] mx-auto mb-2" />
            <p className="text-sm text-[#ff0000]">Failed to load ops data</p>
            <p className="text-xs text-[#808080] mt-1">Check OPS_FEED_URL configuration</p>
          </div>
        )}

        {/* Proof Bar Progress */}
        {data && (
          <>
            <section className="border border-[#1a1a1a] bg-[#0d0d0d] rounded p-4">
              <h2 className="text-sm font-bold text-[#00ff00] mb-3 flex items-center gap-2">
                <Shield className="h-4 w-4" />
                PROOF BAR PROGRESS
              </h2>
              <div className="space-y-3">
                <div>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-[#808080]">Overall Progress</span>
                    <span className="text-[#00ff00] font-bold">{proofBarProgress}%</span>
                  </div>
                  <div className="h-2 bg-[#1a1a1a] rounded overflow-hidden">
                    <div
                      className="h-full bg-[#00ff00] transition-all"
                      style={{ width: `${proofBarProgress}%` }}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                  <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-2">
                    <p className="text-[10px] text-[#808080] uppercase">Clean Sessions</p>
                    <p className="text-lg font-bold text-[#e0e0e0] mt-1">
                      {data.proof_bar.clean_paper_sessions}
                      <span className="text-xs text-[#606060]"> / 10</span>
                    </p>
                  </div>
                  <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-2">
                    <p className="text-[10px] text-[#808080] uppercase">Scored Setups</p>
                    <p className="text-lg font-bold text-[#e0e0e0] mt-1">
                      {data.proof_bar.scored_setups}
                      <span className="text-xs text-[#606060]"> / 20</span>
                    </p>
                  </div>
                  <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-2">
                    <p className="text-[10px] text-[#808080] uppercase">Avg R-Multiple</p>
                    <p className="text-lg font-bold text-[#00ff00] mt-1">
                      {data.proof_bar.avg_r?.toFixed(2) ?? "N/A"}
                    </p>
                  </div>
                  <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-2">
                    <p className="text-[10px] text-[#808080] uppercase">Rule Breaks</p>
                    <p
                      className={`text-lg font-bold mt-1 ${
                        data.proof_bar.rule_breaks === 0 ? "text-[#00ff00]" : "text-[#ff0000]"
                      }`}
                    >
                      {data.proof_bar.rule_breaks}
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* Strike & Lockout Tracker */}
            <section className="border border-[#1a1a1a] bg-[#0d0d0d] rounded p-4">
              <h2 className="text-sm font-bold text-[#00ff00] mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4" />
                STRIKE & LOCKOUT TRACKER
              </h2>
              <div className="space-y-3">
                {data.lockout.active ? (
                  <div className="border border-[#ff0000] bg-[#1a0000] rounded p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <XCircle className="h-4 w-4 text-[#ff0000]" />
                      <span className="text-sm font-bold text-[#ff0000]">LOCKOUT ACTIVE</span>
                    </div>
                    <p className="text-xs text-[#e0e0e0]">End: {data.lockout.end_date ?? "Unknown"}</p>
                    <p className="text-xs text-[#808080] mt-1">{data.lockout.reason ?? "No reason given"}</p>
                  </div>
                ) : (
                  <div className="border border-[#00ff00] bg-[#001a00] rounded p-3">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-[#00ff00]" />
                      <span className="text-sm font-bold text-[#00ff00]">NO LOCKOUT</span>
                    </div>
                  </div>
                )}

                <div>
                  <p className="text-xs text-[#808080] uppercase mb-2">Recent Strikes</p>
                  {data.strikes.length === 0 ? (
                    <p className="text-xs text-[#606060] italic">No strikes recorded</p>
                  ) : (
                    <div className="space-y-2">
                      {data.strikes.slice(0, 5).map((strike, i) => (
                        <div
                          key={i}
                          className={`border ${
                            strike.severity === "major"
                              ? "border-[#ff0000] bg-[#1a0000]"
                              : "border-[#ffaa00] bg-[#1a1000]"
                          } rounded p-2`}
                        >
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-[#e0e0e0]">{strike.date}</span>
                            <Badge
                              variant={strike.severity === "major" ? "bear" : "warn"}
                              className="text-[10px]"
                            >
                              {strike.severity.toUpperCase()}
                            </Badge>
                          </div>
                          <p className="text-xs text-[#808080] mt-1">{strike.reason}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </section>

            {/* Today's Paper Journal */}
            <section className="border border-[#1a1a1a] bg-[#0d0d0d] rounded p-4">
              <h2 className="text-sm font-bold text-[#00ff00] mb-3 flex items-center gap-2">
                <Clock className="h-4 w-4" />
                TODAY'S PAPER JOURNAL
              </h2>
              {data.today_journal.length === 0 ? (
                <p className="text-xs text-[#606060] italic">No trades today</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#1a1a1a]">
                        <th className="text-left py-2 px-2 text-[#808080] font-normal">Symbol</th>
                        <th className="text-left py-2 px-2 text-[#808080] font-normal">Direction</th>
                        <th className="text-right py-2 px-2 text-[#808080] font-normal">Entry</th>
                        <th className="text-right py-2 px-2 text-[#808080] font-normal">Exit</th>
                        <th className="text-right py-2 px-2 text-[#808080] font-normal">R</th>
                        <th className="text-left py-2 px-2 text-[#808080] font-normal">Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.today_journal.map((row, i) => {
                        const isPreHoldout = row.notes.includes("Pre-holdout");
                        return (
                          <tr key={i} className="border-b border-[#1a1a1a]">
                            <td className="py-2 px-2">
                              <div className="flex items-center gap-2">
                                <span className="text-[#00ff00]">{row.symbol}</span>
                                {isPreHoldout && (
                                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#ffaa00]/20 border border-[#ffaa00]/40 text-[#ffaa00] uppercase font-bold">
                                    Pre-Holdout
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="py-2 px-2">
                              <span
                                className={
                                  row.direction === "long" ? "text-[#00ff00]" : "text-[#ff0000]"
                                }
                              >
                                {row.direction.toUpperCase()}
                              </span>
                            </td>
                            <td className="py-2 px-2 text-right text-[#e0e0e0]">
                              {row.entry_price.toFixed(2)}
                            </td>
                            <td className="py-2 px-2 text-right text-[#e0e0e0]">
                              {row.exit_price?.toFixed(2) ?? "—"}
                            </td>
                            <td className="py-2 px-2 text-right">
                              {row.r_multiple !== null ? (
                                <span
                                  className={
                                    row.r_multiple >= 0 ? "text-[#00ff00]" : "text-[#ff0000]"
                                  }
                                >
                                  {row.r_multiple.toFixed(2)}R
                                </span>
                              ) : (
                                <span className="text-[#606060]">—</span>
                              )}
                            </td>
                            <td className="py-2 px-2 text-[#808080] max-w-xs truncate">
                              {row.notes}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* System Health */}
            <section className="border border-[#1a1a1a] bg-[#0d0d0d] rounded p-4">
              <h2 className="text-sm font-bold text-[#00ff00] mb-3 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />
                SYSTEM HEALTH
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-3">
                  <p className="text-[10px] text-[#808080] uppercase mb-1">Tick Recorder</p>
                  {data.system_health.tick_recorder_last_write ? (
                    <>
                      <p className="text-xs text-[#e0e0e0]">
                        {formatTimestamp(data.system_health.tick_recorder_last_write)}
                      </p>
                      <p className="text-[10px] text-[#606060] mt-1">
                        {formatDuration(
                          calculateAgeSeconds(data.system_health.tick_recorder_last_write)
                        )}{" "}
                        ago
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-[#ff0000]">No data</p>
                  )}
                </div>
                <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-3">
                  <p className="text-[10px] text-[#808080] uppercase mb-1">Flow Feed</p>
                  {data.system_health.flow_feed_age_seconds !== null ? (
                    <p
                      className={`text-xs ${
                        data.system_health.flow_feed_age_seconds > 120
                          ? "text-[#ff0000]"
                          : data.system_health.flow_feed_age_seconds > 60
                          ? "text-[#ffaa00]"
                          : "text-[#00ff00]"
                      }`}
                    >
                      {formatDuration(data.system_health.flow_feed_age_seconds)} old
                    </p>
                  ) : (
                    <p className="text-xs text-[#ff0000]">No data</p>
                  )}
                </div>
                <div className="border border-[#1a1a1a] bg-[#0a0a0a] rounded p-3">
                  <p className="text-[10px] text-[#808080] uppercase mb-1">IB Gateway</p>
                  <div className="flex items-center gap-2">
                    {data.system_health.ib_gateway_status === "connected" ? (
                      <>
                        <CheckCircle2 className="h-3 w-3 text-[#00ff00]" />
                        <span className="text-xs text-[#00ff00]">CONNECTED</span>
                      </>
                    ) : data.system_health.ib_gateway_status === "disconnected" ? (
                      <>
                        <XCircle className="h-3 w-3 text-[#ff0000]" />
                        <span className="text-xs text-[#ff0000]">DISCONNECTED</span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="h-3 w-3 text-[#ffaa00]" />
                        <span className="text-xs text-[#ffaa00]">UNKNOWN</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
