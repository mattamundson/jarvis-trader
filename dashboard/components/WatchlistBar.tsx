import { TrendingUp, TrendingDown } from "lucide-react";
import { formatCurrency, formatPercent } from "@/lib/utils";
import type { WatchlistItem } from "@/lib/api";

interface WatchlistBarProps {
  items: WatchlistItem[];
}

export function WatchlistBar({ items }: WatchlistBarProps) {
  return (
    <div className="flex items-center gap-4 overflow-x-auto rounded-xl border border-border bg-card px-4 py-3 scrollbar-none">
      {items.map((item) => (
        <WatchlistTicker key={item.symbol} item={item} />
      ))}
      {items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Engine not connected — start{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            uvicorn main:app --port 8010
          </code>
        </p>
      )}
    </div>
  );
}

function WatchlistTicker({ item }: { item: WatchlistItem }) {
  const up = (item.change_pct ?? 0) >= 0;
  const Icon = up ? TrendingUp : TrendingDown;

  return (
    <div className="flex items-center gap-2 shrink-0">
      <div>
        <p className="font-mono text-sm font-bold">{item.symbol}</p>
        <p className="text-xs text-muted-foreground">{item.name}</p>
      </div>
      <div className="text-right">
        <p className="tabular-nums text-sm font-medium">
          {item.last_price != null ? formatCurrency(item.last_price) : "—"}
        </p>
        {item.change_pct != null && (
          <div className={`flex items-center gap-0.5 text-xs ${up ? "text-bull" : "text-bear"}`}>
            <Icon className="h-3 w-3" />
            <span className="tabular-nums">{formatPercent(item.change_pct)}</span>
          </div>
        )}
      </div>
      <div className="ml-2 h-6 w-px bg-border shrink-0" />
    </div>
  );
}
