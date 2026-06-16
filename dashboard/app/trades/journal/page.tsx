"use client";

import React, { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { fetchTradeJournal, type TradeJournalEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

const REFRESH_MS = 30_000;

export default function TradeJournalPage() {
  const [limit] = useState(100);

  const { data, error, isLoading, mutate } = useSWR(
    ["trade-journal", limit],
    () => fetchTradeJournal(undefined, undefined, limit),
    { refreshInterval: REFRESH_MS }
  );

  const formatDate = (dateString: string): string => {
    try {
      const date = new Date(dateString);
      return date.toLocaleString("en-US", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateString;
    }
  };

  const formatNumber = (num: number | null | undefined, decimals: number = 2): string => {
    if (num === null || num === undefined) return "—";
    return num.toFixed(decimals);
  };

  const getSideBadgeVariant = (side: string): "bull" | "bear" | "warn" | "info" | "neutral" => {
    if (!side) return "neutral";
    const lowerSide = side.toLowerCase();
    if (lowerSide.includes("buy") || lowerSide.includes("long")) return "bull";
    if (lowerSide.includes("sell") || lowerSide.includes("short")) return "bear";
    return "neutral";
  };

  const getStageBadgeVariant = (stage: string | null): "bull" | "bear" | "warn" | "info" | "neutral" => {
    if (!stage) return "neutral";
    const lowerStage = stage.toLowerCase();
    if (lowerStage.includes("technical")) return "info";
    if (lowerStage.includes("debate")) return "warn";
    if (lowerStage.includes("news")) return "bull";
    if (lowerStage.includes("risk")) return "bear";
    return "neutral";
  };

  return (
    <div className="w-full min-h-screen bg-background text-foreground p-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/trades">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-foreground">Trade Journal</h1>
            <p className="text-sm text-muted-foreground">
              Paper trades with signal provenance and pipeline attribution
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void mutate()}
          disabled={isLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {isLoading && !data && (
        <Card>
          <CardContent className="pt-8 pb-8">
            <div className="flex items-center justify-center">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-foreground" />
              <span className="ml-4 text-muted-foreground">Loading trade journal...</span>
            </div>
          </CardContent>
        </Card>
      )}

      {error && (
        <Card className="border-bear/30 bg-bear/5">
          <CardContent className="pt-6">
            <p className="text-bear">Error loading trade journal: {String(error)}</p>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Date</th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Symbol</th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Side</th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground">P&L</th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Regime</th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Stage</th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground">Bull</th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground">Bear</th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground">Conf</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.map((trade: TradeJournalEntry) => (
                <tr key={trade.trade_id} className="hover:bg-muted/20">
                  <td className="px-4 py-3 text-foreground">
                    {formatDate(trade.exit_time || trade.entry_time)}
                  </td>
                  <td className="px-4 py-3 font-mono font-semibold">{trade.symbol}</td>
                  <td className="px-4 py-3">
                    <Badge variant={getSideBadgeVariant(trade.side)}>{trade.side}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {trade.pnl !== null ? (
                      <span className={trade.pnl > 0 ? "text-bull font-semibold" : "text-bear font-semibold"}>
                        {trade.pnl > 0 && "+"}{formatNumber(trade.pnl, 2)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {trade.regime_tier ? `T${trade.regime_tier}` : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {trade.deciding_stage ? (
                      <Badge variant={getStageBadgeVariant(trade.deciding_stage)}>
                        {trade.deciding_stage.substring(0, 3)}
                      </Badge>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">{formatNumber(trade.bull_score, 1)}</td>
                  <td className="px-4 py-3 text-right">{formatNumber(trade.bear_score, 1)}</td>
                  <td className="px-4 py-3 text-right">
                    {trade.debate_confidence ? `${formatNumber(trade.debate_confidence * 100, 0)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="pt-8 pb-8">
            <p className="text-center text-muted-foreground">No trades in journal yet</p>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-muted-foreground">Total</p>
              <p className="text-2xl font-bold text-foreground">{data.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-muted-foreground">Wins</p>
              <p className="text-2xl font-bold text-bull">
                {data.filter((t) => (t.pnl ?? 0) > 0).length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-muted-foreground">Losses</p>
              <p className="text-2xl font-bold text-bear">
                {data.filter((t) => (t.pnl ?? 0) < 0).length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-muted-foreground">Total P&L</p>
              {(() => {
                const totalPnl = data.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
                return (
                  <p className={`text-2xl font-bold ${totalPnl > 0 ? "text-bull" : totalPnl < 0 ? "text-bear" : "text-muted-foreground"}`}>
                    {totalPnl >= 0 ? "+" : ""}{formatNumber(totalPnl, 2)}
                  </p>
                );
              })()}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
