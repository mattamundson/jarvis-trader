"use client";

import React from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchTradeJournal, type TradeJournalEntry } from "@/lib/api";
import { Calendar, TrendingUp, AlertTriangle, CheckCircle2 } from "lucide-react";

const REFRESH_MS = 30_000;
const PROOF_BAR_TARGET = 20;

interface Setup {
  date: string;
  symbol: string;
  setup: string;
  rResult: number | null;
  pnl: number | null;
  ruleBreak: boolean;
  side: string;
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
        const entryPrice = t.entry_price;
        const exitPrice = t.exit_price;
        const riskPerUnit = exitPrice && entryPrice 
          ? Math.abs(entryPrice - exitPrice) * 0.02
          : entryPrice * 0.02;
        
        const rResult = riskPerUnit && riskPerUnit > 0 && t.pnl !== null
          ? t.pnl / (riskPerUnit * t.quantity)
          : null;
        
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
          rResult,
          pnl: t.pnl,
          ruleBreak: false,
          side: t.side,
        };
      });
  }, [data]);

  const avgR = React.useMemo(() => {
    const validRs = setups.filter((s) => s.rResult !== null).map((s) => s.rResult!);
    return validRs.length > 0 ? validRs.reduce((a, b) => a + b, 0) / validRs.length : null;
  }, [setups]);

  const cleanSessions = React.useMemo(() => {
    return setups.filter((s) => !s.ruleBreak).length;
  }, [setups]);

  const progress = setups.length;
  const progressPct = Math.min((progress / PROOF_BAR_TARGET) * 100, 100);

  const formatR = (r: number | null): string => {
    if (r === null) return "—";
    return `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`;
  };

  const formatPnL = (pnl: number | null): string => {
    if (pnl === null) return "—";
    return `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6 font-mono">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-foreground tracking-tight">
            Paper Trading Journal
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Scored setups toward 20-setup proof bar
          </p>
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
                  <div
                    className={`text-3xl font-bold ${
                      avgR !== null
                        ? avgR >= 0
                          ? "text-bull"
                          : "text-bear"
                        : "text-muted-foreground"
                    }`}
                  >
                    {avgR !== null ? formatR(avgR) : "—"}
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Target: +1.0R minimum
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Clean Sessions
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold">{cleanSessions}</div>
                  <div className="text-xs text-muted-foreground mt-2">
                    No rule breaks
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Rule Breaks
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-bear">
                    {setups.filter((s) => s.ruleBreak).length}
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Flags tracked
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
                          <th className="px-4 py-3 text-right font-semibold text-muted-foreground">
                            P&L
                          </th>
                          <th className="px-4 py-3 text-center font-semibold text-muted-foreground">
                            Flags
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
                              <span
                                className={
                                  setup.rResult !== null
                                    ? setup.rResult >= 0
                                      ? "text-bull font-semibold"
                                      : "text-bear font-semibold"
                                    : "text-muted-foreground"
                                }
                              >
                                {formatR(setup.rResult)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span
                                className={
                                  setup.pnl !== null
                                    ? setup.pnl >= 0
                                      ? "text-bull font-semibold"
                                      : "text-bear font-semibold"
                                    : "text-muted-foreground"
                                }
                              >
                                {formatPnL(setup.pnl)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              {setup.ruleBreak ? (
                                <Badge variant="warn">
                                  <AlertTriangle className="h-3 w-3" />
                                </Badge>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
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
