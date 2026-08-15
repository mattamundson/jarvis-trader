"use client";

import { TradingViewWidget } from "@/components/charts/TradingViewWidget";
import { MARKET_CONTEXT } from "@/lib/chart-class";

/**
 * Macro/market-context tiles rendered with TradingView embeds — the surface where
 * TV's hosted data is appropriate (equities, indices, macro, crypto are real-time
 * enough on the free tier; CME futures are NOT, which is why they live elsewhere).
 */
export function MarketContextStrip({
  height = 220,
  title = "Market Context",
}: {
  height?: number;
  title?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </p>
        <span className="font-mono text-[10px] text-muted-foreground/70">
          TradingView · may be delayed
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {MARKET_CONTEXT.map((m) => (
          <div key={m.tv}>
            <p className="mb-1 font-mono text-[11px] text-muted-foreground">{m.label}</p>
            <TradingViewWidget tvSymbol={m.tv} timeframe="1h" height={height} />
          </div>
        ))}
      </div>
    </div>
  );
}
