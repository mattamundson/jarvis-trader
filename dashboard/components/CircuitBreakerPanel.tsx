"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine, type CircuitBreakerState } from "@/lib/api";

function isLimitTripped(value: number, limit: number): boolean {
  return Math.abs(value) >= Math.abs(limit);
}

function GaugeState({ label, tripped }: { label: string; tripped: boolean }) {
  return (
    <div className="flex items-center justify-between rounded border border-border bg-muted/20 px-3 py-2">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <Badge variant={tripped ? "bear" : "bull"}>{tripped ? "TRIPPED" : "NORMAL"}</Badge>
    </div>
  );
}

export function CircuitBreakerPanel() {
  const { data, error, isLoading } = useSWR<CircuitBreakerState>(
    "/safety/circuit-breakers",
    (path: string) => fetchEngine<CircuitBreakerState>(path),
  );

  if (error || (!isLoading && !data)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Circuit Breakers</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Circuit breaker data unavailable</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Circuit Breakers</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading circuit breaker data...</p>
        </CardContent>
      </Card>
    );
  }

  const dailyLossTripped = isLimitTripped(data.daily_pnl, data.daily_limit);
  const drawdownTripped = isLimitTripped(data.drawdown_pct, data.drawdown_limit_pct);
  const halted = data.kill_switch_active || !data.all_clear || dailyLossTripped || drawdownTripped;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Circuit Breakers</CardTitle>
          <Badge variant={halted ? "bear" : "bull"}>{halted ? "HALTED" : "All Clear"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-sm font-medium">
          Kill Switch: {data.kill_switch_active ? "Active" : "Inactive"}
        </div>
        <GaugeState label="Daily P&L" tripped={dailyLossTripped} />
        <GaugeState label="Drawdown" tripped={drawdownTripped} />
      </CardContent>
    </Card>
  );
}
