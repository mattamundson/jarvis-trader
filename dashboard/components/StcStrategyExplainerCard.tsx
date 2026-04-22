"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function StcStrategyExplainerCard() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>STC Strategy Overview</CardTitle>
          <Badge variant="info">Reference</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Section 1: Indicator Description */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Indicator Description
          </p>
          <p className="text-sm text-foreground leading-relaxed">
            The Schaff Trend Cycle (STC) combines MACD and Stochastic oscillators to identify
            cyclical trends. It oscillates 0–100: below 25 = oversold (buy zone), above 75 =
            overbought (sell zone).
          </p>
        </div>

        {/* Section 2: Signal Generation */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Signal Generation
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* BUY LONG */}
            <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-3">
              <p className="text-xs font-bold text-green-400 mb-1">BUY LONG</p>
              <p className="text-xs text-foreground/80 leading-snug">
                STC crosses above 15 (oversold threshold) + BULLISH regime + MTF alignment
              </p>
            </div>

            {/* SELL SHORT */}
            <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3">
              <p className="text-xs font-bold text-red-400 mb-1">SELL SHORT</p>
              <p className="text-xs text-foreground/80 leading-snug">
                STC crosses below 83 (overbought threshold) + BEARISH regime + MTF alignment
              </p>
            </div>

            {/* HOLD */}
            <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/10 p-3">
              <p className="text-xs font-bold text-yellow-400 mb-1">HOLD</p>
              <p className="text-xs text-foreground/80 leading-snug">
                STC in neutral zone (15–83) or conflicting regime signals
              </p>
            </div>

            {/* EXIT */}
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <p className="text-xs font-bold text-muted-foreground mb-1">EXIT</p>
              <p className="text-xs text-foreground/80 leading-snug">
                Profit target hit (1.5x ATR) or stop loss hit (0.7x ATR)
              </p>
            </div>
          </div>
        </div>

        {/* Section 3: Multi-Timeframe Alignment */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Multi-Timeframe Alignment
          </p>
          <ul className="space-y-1.5">
            <li className="flex items-start gap-2 text-xs text-foreground/80">
              <span className="font-mono font-semibold text-accent w-8 shrink-0">1H</span>
              <span>Short-term signal generation</span>
            </li>
            <li className="flex items-start gap-2 text-xs text-foreground/80">
              <span className="font-mono font-semibold text-accent w-8 shrink-0">4H</span>
              <span>Intermediate trend confirmation</span>
            </li>
            <li className="flex items-start gap-2 text-xs text-foreground/80">
              <span className="font-mono font-semibold text-accent w-8 shrink-0">1D</span>
              <span>Macro trend filter</span>
            </li>
            <li className="flex items-start gap-2 text-xs text-muted-foreground italic pt-1">
              <span className="w-8 shrink-0" />
              <span>All 3 timeframes must align for highest confidence trades</span>
            </li>
          </ul>
        </div>

        {/* Section 4: Risk Parameters */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Risk Parameters
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Oversold</p>
              <p className="font-mono text-sm font-semibold text-foreground">&lt; 15</p>
            </div>
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Overbought</p>
              <p className="font-mono text-sm font-semibold text-foreground">&gt; 83</p>
            </div>
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Stop</p>
              <p className="font-mono text-sm font-semibold text-foreground">ATR × 0.70</p>
            </div>
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Target</p>
              <p className="font-mono text-sm font-semibold text-foreground">ATR × 1.50</p>
            </div>
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">R:R Ratio</p>
              <p className="font-mono text-sm font-semibold text-foreground">1 : 2.14</p>
            </div>
            <div className="rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Win Rate</p>
              <p className="font-mono text-sm font-semibold text-green-400">67.3%</p>
            </div>
            <div className="col-span-2 rounded-md border border-border bg-background px-3 py-2 text-center">
              <p className="text-[10px] text-muted-foreground mb-0.5">Sample Size</p>
              <p className="font-mono text-sm font-semibold text-foreground">847 trades (backtest)</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
