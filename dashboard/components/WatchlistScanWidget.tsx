"use client";
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";

type TFResult = { alignment: string; stc_value: number; signal: string };

type SymbolResult = {
  symbol: string;
  recommendation: "BUY" | "SELL" | "WAIT";
  alignment: string;
  timeframes: Record<string, TFResult>;
  error?: string | null;
};

type ScanData = {
  symbols: SymbolResult[];
  market_bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  buy_count: number;
  sell_count: number;
  wait_count: number;
  scanned_at: string;
};

const REC_VARIANT: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  BUY: "bull",
  SELL: "bear",
  WAIT: "neutral",
};

const BIAS_VARIANT: Record<string, "bull" | "bear" | "neutral"> = {
  BULLISH: "bull",
  BEARISH: "bear",
  NEUTRAL: "neutral",
};

export function WatchlistScanWidget({ symbols = "MES,MNQ,MCL" }: { symbols?: string }) {
  const [data, setData] = useState<ScanData | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastScan, setLastScan] = useState<string | null>(null);

  const scan = () => {
    setLoading(true);
    fetchEngine(`/watchlist/scan?symbols=${encodeURIComponent(symbols)}`)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setLastScan(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    scan();
    const id = setInterval(scan, 300_000); // refresh every 5 min
    return () => clearInterval(id);
  }, [symbols]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Watchlist Scan</CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <Badge variant={BIAS_VARIANT[data.market_bias] ?? "neutral"}>
                {data.market_bias}
              </Badge>
            )}
            <button
              onClick={scan}
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Re-scan"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastScan && (
          <p className="text-xs text-muted-foreground">Last scan: {lastScan}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {!data ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-12 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : (
          <>
            <div className="divide-y divide-border">
              {data.symbols.map((s) => (
                <div key={s.symbol} className="px-4 py-2.5 flex items-center justify-between">
                  <div>
                    <span className="text-sm font-mono font-semibold">{s.symbol}</span>
                    {s.error ? (
                      <p className="text-xs text-muted-foreground">{s.error}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground">{s.alignment}</p>
                    )}
                  </div>
                  <Badge variant={REC_VARIANT[s.recommendation] ?? "neutral"}>
                    {s.recommendation}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="px-4 py-2 border-t border-border bg-muted/30 flex gap-3 text-xs text-muted-foreground">
              <span className="text-green-500">{data.buy_count} BUY</span>
              <span className="text-red-500">{data.sell_count} SELL</span>
              <span>{data.wait_count} WAIT</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
