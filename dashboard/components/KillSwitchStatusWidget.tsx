"use client";

import { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface SafetyStatus {
  kill_switch_active: boolean;
  daily_pnl: number;
  daily_pnl_limit: number;
  max_drawdown_limit: number;
  circuit_breaker_triggered: boolean;
  trading_enabled: boolean;
  reason: string | null;
}

export function KillSwitchStatusWidget() {
  const [data, setData] = useState<SafetyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  async function fetchStatus() {
    try {
      const res = await fetch(`${ENGINE_URL}/safety/status`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: SafetyStatus = await res.json();
      setData(json);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 30_000);
    return () => clearInterval(id);
  }, []);

  // Loading skeleton
  if (loading) {
    return (
      <Card className="p-5 space-y-3 animate-pulse">
        <div className="h-4 w-48 bg-muted rounded" />
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-8 bg-muted rounded" />
          ))}
        </div>
      </Card>
    );
  }

  // Error state
  if (error || !data) {
    return (
      <Card className="p-5 border-red-500/40 bg-red-500/5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
          Kill Switch &amp; Circuit Breakers
        </p>
        <p className="text-sm text-red-400 font-medium">
          Safety status unavailable — engine may be offline
        </p>
      </Card>
    );
  }

  const pnlIsNegative = data.daily_pnl < 0;
  const pnlColor = pnlIsNegative ? "text-red-400" : "text-green-400";
  const pnlFormatted = `${pnlIsNegative ? "-" : ""}$${Math.abs(data.daily_pnl).toFixed(2)}`;
  const limitFormatted = `-$${Math.abs(data.daily_pnl_limit).toFixed(2)} limit`;

  return (
    <Card className="p-5 space-y-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Kill Switch &amp; Circuit Breakers
      </p>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        {/* Kill Switch Status */}
        <div className="space-y-1">
          <span className="text-[11px] text-muted-foreground">Kill Switch</span>
          <div>
            {data.kill_switch_active ? (
              <Badge variant="bear">KILL SWITCH ACTIVE</Badge>
            ) : (
              <Badge variant="bull">Trading Active</Badge>
            )}
          </div>
        </div>

        {/* Circuit Breaker */}
        <div className="space-y-1">
          <span className="text-[11px] text-muted-foreground">Circuit Breaker</span>
          <div>
            {data.circuit_breaker_triggered ? (
              <Badge variant="warn">CIRCUIT BREAKER</Badge>
            ) : (
              <Badge variant="neutral">Normal</Badge>
            )}
          </div>
        </div>

        {/* Daily P&L vs Limit */}
        <div className="space-y-1">
          <span className="text-[11px] text-muted-foreground">Daily P&amp;L</span>
          <p className={`text-sm font-semibold font-mono ${pnlColor}`}>
            {pnlFormatted}{" "}
            <span className="text-muted-foreground font-normal text-xs">
              / {limitFormatted}
            </span>
          </p>
        </div>

        {/* Trading Enabled */}
        <div className="space-y-1">
          <span className="text-[11px] text-muted-foreground">Trading</span>
          <p
            className={`text-sm font-semibold ${
              data.trading_enabled ? "text-green-400" : "text-red-400"
            }`}
          >
            {data.trading_enabled ? "Enabled" : "Disabled"}
          </p>
        </div>
      </div>

      {/* Reason (shown only when non-null) */}
      {data.reason !== null && data.reason !== undefined && (
        <p className="text-[11px] text-muted-foreground italic border-t border-border/50 pt-2">
          {data.reason}
        </p>
      )}
    </Card>
  );
}
