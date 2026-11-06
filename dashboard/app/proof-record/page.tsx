"use client";

import React from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { localFetch } from "@/lib/api";
import { Calendar, TrendingUp, AlertCircle, Info } from "lucide-react";

const REFRESH_MS = 30_000;

interface ProofSetup {
  date: string;
  setup: string;
  side: string;
  trigger: string;
  entry_time: string;
  entry: number;
  stop: number;
  target: number;
  exit_time: string;
  exit: number;
  exit_reason: string;
  R: number;
  rule_breaks?: string[];
  status: string;
  counted: boolean;
}

interface ProofRecordData {
  available: boolean;
  source?: string;
  error?: string;
  goal_setups: number;
  counted: number;
  avg_r: number | null;
  total_r: number | null;
  wins: number;
  losses: number;
  generated_ct?: string;
  setups: ProofSetup[];
}

export default function ProofRecordPage() {
  const { data, error, isLoading } = useSWR<ProofRecordData>(
    "/api/proof-record",
    localFetch,
    { refreshInterval: REFRESH_MS }
  );

  const progress = data?.counted || 0;
  const goal = data?.goal_setups || 20;
  const progressPct = Math.min((progress / goal) * 100, 100);

  const formatR = (r: number): string => {
    return `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`;
  };

  const formatAvgR = (r: number | null): string => {
    if (r === null) return "n/a";
    return formatR(r);
  };

  const formatRuleBreaks = (breaks?: string[]): string => {
    if (!breaks || breaks.length === 0) return "—";
    return breaks.join(", ");
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6 font-mono">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-foreground tracking-tight">
            ES Proof Record
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Progress toward 20 scored setups with stop-loss data
          </p>
        </div>

        {isLoading && !data && (
          <Card className="mb-6">
            <CardContent className="pt-8 pb-8">
              <div className="flex items-center justify-center">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-foreground" />
                <span className="ml-4 text-muted-foreground">Loading proof record...</span>
              </div>
            </CardContent>
          </Card>
        )}

        {error && (
          <Card className="mb-6 border-bear/30 bg-bear/5">
            <CardContent className="pt-6">
              <p className="text-bear">Error loading proof record: {String(error)}</p>
            </CardContent>
          </Card>
        )}

        {data && !data.available && (
          <Card className="mb-6 border-warn/30 bg-warn/5">
            <CardContent className="pt-6">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-warn" />
                <p className="text-warn">{data.error || "Proof record data unavailable"}</p>
              </div>
              <p className="text-sm text-muted-foreground mt-2">
                Configure JARVIS_PROOF_RECORD_PATH or PROOF_RECORD_PATH to enable this page.
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
                      / {goal}
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
                  <div className={`text-2xl font-bold ${
                    data.avg_r === null 
                      ? "text-muted-foreground" 
                      : data.avg_r >= 0 
                        ? "text-bull" 
                        : "text-bear"
                  }`}>
                    {formatAvgR(data.avg_r)}
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
                    Win/Loss Record
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    <span className="text-bull">{data.wins}W</span>
                    <span className="text-muted-foreground mx-1">/</span>
                    <span className="text-bear">{data.losses}L</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    {data.wins + data.losses > 0 
                      ? `${((data.wins / (data.wins + data.losses)) * 100).toFixed(1)}% win rate`
                      : "No completed setups"}
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
                  <div className="text-sm font-semibold">
                    {data.available ? (
                      <Badge variant="bull" className="text-xs">
                        {data.source === "file" ? "File" : "Engine"}
                      </Badge>
                    ) : (
                      <Badge variant="neutral" className="text-xs">
                        Unavailable
                      </Badge>
                    )}
                  </div>
                  {data.generated_ct && (
                    <div className="text-xs text-muted-foreground mt-2">
                      Updated: {new Date(data.generated_ct).toLocaleString()}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {data.setups.length === 0 ? (
              <Card>
                <CardContent className="pt-8 pb-8">
                  <div className="text-center">
                    <Calendar className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                    <p className="text-lg font-medium text-foreground mb-2">
                      No scored setups yet
                    </p>
                    <p className="text-sm text-muted-foreground">
                      Scored ES setups with stop-loss data will appear here
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
                            Setup
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Side
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Trigger
                          </th>
                          <th className="px-4 py-3 text-right font-semibold text-muted-foreground">
                            R Result
                          </th>
                          <th className="px-4 py-3 text-center font-semibold text-muted-foreground">
                            Status
                          </th>
                          <th className="px-4 py-3 text-left font-semibold text-muted-foreground">
                            Rule Breaks
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {data.setups.map((setup, idx) => (
                          <tr key={idx} className="hover:bg-muted/20">
                            <td className="px-4 py-3 text-foreground">{setup.date}</td>
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
                            <td className="px-4 py-3 text-muted-foreground text-xs">
                              {setup.trigger}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className={`font-semibold ${
                                setup.R >= 0 ? "text-bull" : "text-bear"
                              }`}>
                                {formatR(setup.R)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <Badge 
                                variant={setup.counted ? "bull" : "neutral"}
                                className="text-xs"
                              >
                                {setup.counted ? "Counted" : setup.status}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-xs text-muted-foreground">
                              {formatRuleBreaks(setup.rule_breaks)}
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
