"use client";

import React from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchScoredSetups, type ScoredSetup } from "@/lib/api";
import { Calendar, TrendingUp, AlertCircle, Info } from "lucide-react";

const REFRESH_MS = 30_000;
const DEFAULT_PROOF_BAR_TARGET = 20;

export default function JournalPage() {
  const { data, error, isLoading } = useSWR(
    "trade-scored-setups",
    () => fetchScoredSetups(),
    { refreshInterval: REFRESH_MS },
  );

  const setups: ScoredSetup[] = React.useMemo(
    () => (data?.available ? [...data.setups].reverse() : []),
    [data],
  );

  const target = data?.goal_setups || DEFAULT_PROOF_BAR_TARGET;
  const progress = data?.available ? data.counted : 0;
  const avgR = data?.available ? data.avg_r : null;
  const progressPct = Math.min((progress / target) * 100, 100);

  const formatR = (r: number | null): string => {
    if (r === null) return "R n/a";
    return `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`;
  };

  const formatAvgR = (r: number | null): string => {
    if (r === null) return "n/a";
    return `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`;
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6 font-mono">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-foreground tracking-tight">
            Trade Journal
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
                <span className="ml-4 text-muted-foreground">
                  Loading journal...
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        {error && (
          <Card className="mb-6 border-bear/30 bg-bear/5">
            <CardContent className="pt-6">
              <p className="text-bear">
                Error loading journal: {String(error)}
              </p>
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
                      / {target}
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
                  <div className="text-2xl font-bold">{formatAvgR(avgR)}</div>
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
                  <div className="text-2xl font-bold text-muted-foreground">
                    n/a
                  </div>
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
                    {data.available && data.age_seconds !== null && data.age_seconds > 3600 && (
                      <Badge variant="warn" className="ml-auto text-xs">
                        Stale
                      </Badge>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-xs text-muted-foreground mt-1">
                    {data.available
                      ? `Tape proof record (${data.source}), as of ${data.generated_ct ?? "unknown"}. ${data.r_basis ?? ""}`
                      : `Proof record unavailable: ${data.error ?? "unknown error"}`}
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
                      Scored setups from the tape proof record will appear here
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
                            Trigger
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
                          <tr
                            key={`${setup.date}-${idx}`}
                            className="hover:bg-muted/20"
                          >
                            <td className="px-4 py-3 text-foreground">
                              {setup.date}
                            </td>
                            <td className="px-4 py-3 text-xs text-muted-foreground">
                              {setup.trigger ?? "—"}
                            </td>
                            <td className="px-4 py-3 text-muted-foreground">
                              {setup.setup}
                            </td>
                            <td className="px-4 py-3">
                              <Badge
                                variant={
                                  setup.side.toLowerCase().includes("long") ||
                                  setup.side.toLowerCase().includes("buy")
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
                                  setup.r_multiple === null
                                    ? "text-muted-foreground text-xs"
                                    : setup.r_multiple >= 0
                                      ? "text-bull font-semibold"
                                      : "text-bear font-semibold"
                                }
                              >
                                {formatR(setup.r_multiple)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <Badge
                                variant={
                                  setup.counted
                                    ? setup.rule_breaks
                                      ? "warn"
                                      : "info"
                                    : "neutral"
                                }
                                className="text-xs"
                              >
                                {setup.counted
                                  ? setup.rule_breaks
                                    ? `${setup.rule_breaks} rule break${setup.rule_breaks > 1 ? "s" : ""}`
                                    : "counted"
                                  : "not counted"}
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
