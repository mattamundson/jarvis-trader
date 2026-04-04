"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import EngineWidget from "@/components/EngineWidget";
import { DiscordIntelligenceStatus } from "@/lib/api";

interface SymbolIntelligence {
  symbol: string;
  discord_signal_active: number;
  discord_win_rate_context: number;
  discord_proximity_entry: number;
  discord_proximity_target: number;
  discord_alignment: number;
}

function getSignalBadgeVariant(
  isActive: number
): "bull" | "bear" | "warn" | "info" | "neutral" {
  return isActive > 0.5 ? "bull" : "neutral";
}

function getAlignmentBadgeVariant(
  alignment: number
): "bull" | "bear" | "warn" | "info" | "neutral" {
  if (alignment > 0.5) return "bull";
  if (alignment < -0.5) return "bear";
  return "neutral";
}

function getAlignmentText(alignment: number): string {
  if (alignment > 0.5) return "ALIGNED";
  if (alignment < -0.5) return "OPPOSED";
  return "NEUTRAL";
}

function SymbolCard({ symbol, data }: { symbol: string; data: SymbolIntelligence }) {
  const isActive = data.discord_signal_active > 0.5;
  const winRate = Math.round(data.discord_win_rate_context * 100);
  const alignment = data.discord_alignment;

  return (
    <div
      className="rounded-lg p-4"
      style={{
        backgroundColor: "#0a0a0a",
        border: "1px solid #1a1a2e",
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-mono font-bold text-sm">{symbol}</h3>
        <Badge variant={getSignalBadgeVariant(data.discord_signal_active)}>
          {isActive ? "ACTIVE" : "INACTIVE"}
        </Badge>
      </div>

      <div className="space-y-2 text-xs font-mono">
        <div className="flex justify-between">
          <span style={{ color: "#888" }}>Win Rate (30d):</span>
          <span style={{ color: "#00ff88" }}>{winRate}%</span>
        </div>

        <div className="flex justify-between">
          <span style={{ color: "#888" }}>Entry Proximity:</span>
          <span style={{ color: "#aaa" }}>
            {data.discord_proximity_entry >= 0 ? "+" : ""}
            {data.discord_proximity_entry.toFixed(2)} ATR
          </span>
        </div>

        <div className="flex justify-between">
          <span style={{ color: "#888" }}>Target Distance:</span>
          <span style={{ color: "#aaa" }}>{data.discord_proximity_target.toFixed(2)} ATR</span>
        </div>

        <div className="flex justify-between items-center pt-2 border-t border-[#1a1a2e]">
          <span style={{ color: "#888" }}>Alignment:</span>
          <Badge variant={getAlignmentBadgeVariant(alignment)}>
            {getAlignmentText(alignment)}
          </Badge>
        </div>
      </div>
    </div>
  );
}

export function DiscordIntelligenceWidget() {
  return (
    <EngineWidget<DiscordIntelligenceStatus>
      endpoint="/discord/intelligence"
      title="Discord Intelligence"
      refreshInterval={30_000}
      render={(data) => {
        const mcl = data.symbols.MCL ? {
          symbol: "MCL",
          ...data.symbols.MCL,
        } as SymbolIntelligence : null;
        const mnq = data.symbols.MNQ ? {
          symbol: "MNQ",
          ...data.symbols.MNQ,
        } as SymbolIntelligence : null;

        return (
          <Card>
            <CardHeader>
              <CardTitle>Discord Intelligence</CardTitle>
              <p className="font-mono text-xs" style={{ color: "#666", marginTop: "8px" }}>
                Corey Auction Tools bot signals · Last: {new Date(data.last_updated).toLocaleTimeString()}
              </p>
            </CardHeader>

            <CardContent>
              {mcl || mnq ? (
                <div className="grid grid-cols-2 gap-3">
                  {mcl && <SymbolCard symbol={mcl.symbol} data={mcl} />}
                  {mnq && <SymbolCard symbol={mnq.symbol} data={mnq} />}
                </div>
              ) : (
                <div
                  className="rounded-lg p-4 text-center"
                  style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
                >
                  <p className="font-mono text-xs" style={{ color: "#666" }}>
                    Discord data unavailable
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        );
      }}
      fallback={
        <div
          className="rounded-lg p-4 text-center"
          style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
        >
          <p className="font-mono text-xs" style={{ color: "#666" }}>
            Discord intelligence unavailable
          </p>
        </div>
      }
    />
  );
}
