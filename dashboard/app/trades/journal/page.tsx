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
    <div className="w-full min-h-screen bg-slate-50 p-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/trades/pending-approvals">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Trade Journal</h1>
            <p className="text-sm text-slate-600">
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
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-200 border-t-slate-900" />
              <span className="ml-4 text-slate-600">Loading trade journal...</span>
            </div>
          </CardContent>
        </Card>
      )}

      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-700">Error loading trade journal: {String(error)}</p>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-100">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Date</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Symbol</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Side</th>
                <th className="px-4 py-3 text-right font-semibold text-slate-700">P&L</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Regime</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Stage</th>
                <th className="px-4 py-3 text-right font-semibold text-slate-700">Bull</th>
                <th className="px-4 py-3 text-right font-semibold text-slate-700">Bear</th>
                <th className="px-4 py-3 text-right font-semibold text-slate-700">Conf</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.map((trade: TradeJournalEntry) => (
                <tr key={trade.trade_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-slate-900">
                    {formatDate(trade.exit_time || trade.entry_time)}
                  </td>
                  <td className="px-4 py-3 font-mono font-semibold">{trade.symbol}</td>
                  <td className="px-4 py-3">
                    <Badge variant={getSideBadgeVariant(trade.side)}>{trade.side}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {trade.pnl !== null ? (
                      <span className={trade.pnl > 0 ? "text-green-600" : "text-red-600"}>
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
            <p className="text-center text-slate-600">No trades in journal yet</p>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-slate-600">Total</p>
              <p className="text-2xl font-bold">{data.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-slate-600">Wins</p>
              <p className="text-2xl font-bold text-green-600">
                {data.filter((t) => (t.pnl ?? 0) > 0).length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-slate-600">Losses</p>
              <p className="text-2xl font-bold text-red-600">
                {data.filter((t) => (t.pnl ?? 0) < 0).length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-slate-600">Total P&L</p>
              <p className={`text-2xl font-bold ${(data.reduce((sum, t) => sum + (t.pnl ?? 0), 0)) > 0 ? "text-green-600" : "text-red-600"}`}>
                {formatNumber(data.reduce((sum, t) => sum + (t.pnl ?? 0), 0), 2)}
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
