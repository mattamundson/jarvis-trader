"use client";

import React from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DataFreshness } from "@/components/DataFreshness";
import { fetchTradeJournal, type TradeJournalEntry } from "@/lib/api";
import { Calendar, TrendingUp, AlertCircle, Info } from "lucide-react";

const REFRESH_MS = 30_000;
const PROOF_BAR_TARGET = 20;

interface Setup {
  date: string;
  symbol: string;
  setup: string;
  rResult: number | null;
  pnl: number | null;
  ruleBreakStatus: "unknown";
  side: string;
  hasValidR: boolean;
}

export default function JournalPage() {
  const { data, error, isLoading } = useSWR(
    "trade-journal-scored",
    () => fetchTradeJournal(undefined, undefined, 100),
    { refreshInterval: REFRESH_MS }
  );

  const setups = React.useMemo<Setup[]>(() => {
    if (!data) return [];
    return data
      .filter((t) => t.exit_time && t.pnl !== null)
      .map((t) => {
        let setupType = "Unknown";
        if (t.strategy_params) {
          try {
            const params = typeof t.strategy_params === "string" 
              ? JSON.parse(t.strategy_params) 
              : t.strategy_params;
            setupType = params?.setup || t.bias || "Unknown";
          } catch {
            setupType = t.bias || "Unknown";
          }
        } else {
          setupType = t.bias || "Unknown";
        }

        return {
          date: new Date(t.exit_time!).toLocaleDateString(),
          symbol: t.symbol,
          setup: setupType,
          rResult: null,
          pnl: t.pnl,
          ruleBreakStatus: "unknown" as const,
          side: t.side,
          hasValidR: false,
        };
      });
  }, [data]);

  const validSetups = React.useMemo(() => {
    return setups.filter((s) => s.hasValidR);
  }, [setups]);

  const avgR = React.useMemo(() => {
    const validRs = validSetups.filter((s) => s.rResult !== null).map((s) => s.rResult!);
    return validRs.length > 0 ? validRs.reduce((a, b) => a + b, 0) / validRs.length : null;
  }, [validSetups]);

  const mostRecentExitTime = React.useMemo(() => {
    if (!data || data.length === 0) return null;
    const exits = data.filter((t) => t.exit_time).map((t) => new Date(t.exit_time!).getTime());
    return exits.length > 0 ? new Date(Math.max(...exits)) : null;
  }, [data]);

  const progress = validSetups.length;
  const progressPct = Math.min((progress / PROOF_BAR_TARGET) * 100, 100);

  const formatR = (hasValidR: boolean): string => {
    return hasValidR ? "—" : "R n/a";
  };

  const formatAvgR = (r: number | null): string => {
    if (r === null) return "n/a";
    return `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`;
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6 font-mono">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground tracking-tight">
              Paper Trading Journal
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Scored setups toward 20-setup proof bar
            </p>
          </div>
          {mostRecentExitTime && (
            <DataFreshness
              source="Trade Journal"
              dataTimestamp={mostRecentExitTime}
              stalenessThresholdMs={24 * 60 * 60 * 1000}
            />
          )}
        </div>

        {isLoading && !data && (
          <Card className="mb-6">
            <CardContent className="pt-8 pb-8">
              <div className="flex items-center justify-center">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-foreground" />
                <span className="ml-4 text-muted-foreground">Loading journal...</span>
              </div>
            </CardContent>
          </Card>
        )}

        {error && (
          <Card className="mb-6 border-bear/30 bg-bear/5">
            <CardContent className="pt-6">
              <p className="text-bear">Error loading journal: {String(error)}</p>
            </CardContent>
          </Card>
        )}

        {data && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <Calendar className="h-3.5 w-3.5" />
                    Scored Setups
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold">
                    {progress}
                    <span className="text-lg text-muted-foreground ml-1">
                      / {PROOF_BAR_TARGET}
                    </span>
                  </div>
                  <div className="mt-2 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-bull transition-all duration-300"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <TrendingUp className="h-3.5 w-3.5" />
                    Average R
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-muted-foreground">
                    {formatAvgR(avgR)}
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Target: +1.0R minimum
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <Info className="h-3.5 w-3.5" />
                    Clean Sessions
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-muted-foreground">n/a</div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Session-level stat (not available)
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Data Source
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-xs text-muted-foreground mt-1">
                    R-multiples require stop loss data not present in current trade records.
                    Scored setups from Hermes tracker are not exposed via API.
                  </div>
                </CardContent>
              </Card>
            </div>

            {setups.length === 0 ? (
              <Card>
                <CardContent className="pt-8 pb-8">
                  <div className="text-center">
                    <Calendar className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                    <p className="text-lg font-medium text-foreground mb-2">
                      No scored setups yet
                    </p>
                    <p className="text-sm text-muted-foreground">
                      Closed trades with completed exits will appear here
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-semibold uppercase tracking-wider">
                    Scored Setups
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="border-b border-border">
                        <tr>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Date
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Symbol
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Setup
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Side
                          </th>
                          <th className="px-4 py-3 text-right font-semibold text-muted-foreground">
                            R Result
                          </th>
                          <th className="px-4 py-3 text-center font-semibold text-muted-foreground">
                            Status
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {setups.map((setup, idx) => (
                          <tr key={idx} className="hover:bg-muted/20">
                            <td className="px-4 py-3 text-foreground">{setup.date}</td>
                            <td className="px-4 py-3 font-semibold">{setup.symbol}</td>
                            <td className="px-4 py-3 text-muted-foreground">
                              {setup.setup}
                            </td>
                            <td className="px-4 py-3">
                              <Badge
                                variant={
                                  setup.side.toLowerCase().includes("buy") ||
                                  setup.side.toLowerCase().includes("long")
                                    ? "bull"
                                    : "bear"
                                }
                              >
                                {setup.side}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className="text-muted-foreground text-xs">
                                {formatR(setup.hasValidR)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <Badge variant="neutral" className="text-xs">
                                unknown
                              </Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
