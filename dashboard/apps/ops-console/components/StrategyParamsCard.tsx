"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StrategyParamsCard() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Strategy Parameters</CardTitle>
        <Badge variant="info">STC v1.0</Badge>
      </CardHeader>
      <CardContent>
        {/* Parameter grid */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm mb-4">
          {/* Instrument */}
          <span className="text-muted-foreground">Instrument</span>
          <span className="font-mono">MES (Micro E-mini S&P)</span>

          {/* Timeframe */}
          <span className="text-muted-foreground">Timeframe</span>
          <span className="font-mono">1H</span>

          {/* OS Threshold */}
          <span className="text-muted-foreground">STC Oversold (OS)</span>
          <span className="font-mono">15</span>

          {/* OB Threshold */}
          <span className="text-muted-foreground">STC Overbought (OB)</span>
          <span className="font-mono">83</span>

          {/* ATR Stop */}
          <span className="text-muted-foreground">ATR Stop Multiplier</span>
          <span className="font-mono">0.70×</span>

          {/* Target 1 */}
          <span className="text-muted-foreground">Target 1 Multiplier</span>
          <span className="font-mono">1.50×</span>

          {/* Regime Filter */}
          <span className="text-muted-foreground">Regime Filter</span>
          <Badge variant="bull" className="w-fit">Enabled (VIX)</Badge>
        </div>

        <p className="text-xs text-muted-foreground mt-3">
          Reference parameters for paper trading validation phase — see the
          "Best Profit Factor / Sharpe / Win Rate" cards below for real
          backtest results.
        </p>
      </CardContent>
    </Card>
  );
}
