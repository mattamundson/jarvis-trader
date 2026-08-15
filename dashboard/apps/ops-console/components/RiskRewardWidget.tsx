"use client";

import React from "react";
import { TrendingUp, Target, RefreshCw, Scale } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface RRLevel {
  variant: BadgeVariant;
  label: string;
  textColor: string;
  description: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getRRLevel(rr: number | null): RRLevel {
  if (rr === null) {
    return {
      variant: "neutral",
      label: "No Data",
      textColor: "text-muted-foreground",
      description: "No closed trades with valid avg loss data.",
    };
  }
  if (rr < 1.0) {
    return {
      variant: "bear",
      label: "Poor",
      textColor: "text-bear",
      description: "Losing more per trade than winning — strategy at risk.",
    };
  }
  if (rr < 1.5) {
    return {
      variant: "warn",
      label: "Below Target",
      textColor: "text-warn",
      description: "Profitable but below the 1.5:1 minimum threshold.",
    };
  }
  if (rr < 2.0) {
    return {
      variant: "warn",
      label: "Getting There",
      textColor: "text-warn",
      description: "Approaching the 2.0:1 target — nearly there.",
    };
  }
  return {
    variant: "bull",
    label: "Target Met",
    textColor: "text-bull",
    description: "R:R meets or exceeds the ATR 1.5x / 0.7x strategy target.",
  };
}

function fmtCurrency(n: number): string {
  const abs = Math.abs(n);
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${abs.toFixed(2)}`;
}

/** Derive avg win / avg loss from honest deduped trades. */
function deriveRR(set: HonestTradeSet): {
  avgWin: number;
  avgLoss: number;
  rrRatio: number | null;
} {
  const winners = set.trades.filter((t) => t.pnl > 0);
  const losers = set.trades.filter((t) => t.pnl < 0);

  const avgWin =
    winners.length > 0
      ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length
      : 0;

  const avgLoss =
    losers.length > 0
      ? Math.abs(losers.reduce((s, t) => s + t.pnl, 0) / losers.length)
      : 0;

  const rrRatio: number | null =
    avgLoss < 0.01 ? null : avgWin === 0 ? 0 : avgWin / avgLoss;

  return { avgWin, avgLoss, rrRatio };
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function RiskRewardWidget() {
  const { honest: set, isLoading: loading, error: loadError, mutate: fetchData } = useHonestTrades(60_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  // ── Derived values ────────────────────────────────────────────────────────

  const { avgWin, avgLoss, rrRatio } = set
    ? deriveRR(set)
    : { avgWin: 0, avgLoss: 0, rrRatio: null };

  const winRate = set ? set.winRate * 100 : 0;
  const profitFactor = set?.profitFactor ?? 0;
  const level = getRRLevel(rrRatio);
  const rrDisplay = rrRatio === null ? "—" : `${rrRatio.toFixed(2)}:1`;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Risk/Reward Ratio</CardTitle>
            <Badge variant={level.variant}>{level.label}</Badge>
          </div>
          <button
            onClick={() => fetchData()}
            disabled={loading}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        <p className="text-xs text-muted-foreground pt-0.5">
          Average risk:reward from deduped closed trades — MES/MGC futures
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {loading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-16 w-36 bg-muted rounded mx-auto" />
            <div className="grid grid-cols-2 gap-4">
              <div className="h-10 bg-muted rounded" />
              <div className="h-10 bg-muted rounded" />
            </div>
            <div className="h-8 bg-muted rounded" />
          </div>
        ) : error ? (
          <p className="text-sm text-bear">Error: {error}</p>
        ) : (
          <>
            {/* ── Large R:R number ─────────────────────────────────────── */}
            <div className="flex flex-col items-center gap-2 py-2">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                Avg Risk:Reward Ratio
              </p>
              <p
                className={`text-6xl font-bold font-mono leading-none ${level.textColor}`}
              >
                {rrDisplay}
              </p>
              {rrRatio === null && (
                <p className="text-xs text-muted-foreground mt-1">
                  Insufficient data — avg loss too small or no closed trades.
                </p>
              )}
              {rrRatio !== null && (
                <p className="text-xs text-muted-foreground text-center max-w-xs">
                  {level.description}
                </p>
              )}
            </div>

            {/* ── Win / Loss comparison ────────────────────────────────── */}
            <div className="rounded-lg border border-border bg-muted/30 px-4 py-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium mb-1.5">
                Avg Trade Outcome
              </p>
              <p className="text-sm font-mono font-medium text-foreground">
                <span className="text-bull">Win: {fmtCurrency(avgWin)}</span>
                <span className="text-muted-foreground mx-2">|</span>
                <span className="text-bear">Loss: -${avgLoss.toFixed(2)}</span>
              </p>
            </div>

            {/* ── Context stats grid ───────────────────────────────────── */}
            <div className="grid grid-cols-2 gap-4 pt-1 border-t border-border">
              {/* Profit Factor */}
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  Profit Factor
                </p>
                <p
                  className={`text-sm font-mono font-bold ${
                    profitFactor >= 2.0
                      ? "text-bull"
                      : profitFactor >= 1.3
                      ? "text-warn"
                      : "text-bear"
                  }`}
                >
                  {profitFactor === null ? "—" : profitFactor.toFixed(2)}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  gross profit / gross loss
                </p>
              </div>

              {/* Win Rate */}
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium flex items-center gap-1">
                  <Target className="h-3 w-3" />
                  Win Rate
                </p>
                <p
                  className={`text-sm font-mono font-bold ${
                    winRate >= 50 ? "text-bull" : winRate >= 40 ? "text-warn" : "text-bear"
                  }`}
                >
                  {winRate.toFixed(1)}%
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {rrRatio !== null && rrRatio < 1.0 && winRate > 60
                    ? "High WR, low R:R — fragile"
                    : rrRatio !== null && rrRatio >= 2.0 && winRate >= 50
                    ? "WR + R:R both healthy"
                    : "target ≥ 50%"}
                </p>
              </div>
            </div>

            {/* ── Strategy target note ─────────────────────────────────── */}
            <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-2.5 flex items-start gap-2">
              <Target className="h-3.5 w-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-semibold text-foreground">Target: &#8805; 2.0</span>
                {" "}(ATR 1.5x / 0.7x strategy — theoretical R:R &#8776; 2.14)
              </p>
            </div>

            {/* ── Dedup caveat ─────────────────────────────────────────── */}
            {set && (
              <p className="text-[10px] text-muted-foreground text-center">
                {dedupCaveat(set)}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
