"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Compass, AlertTriangle } from "lucide-react";
import { fetchAuctionBias, type AuctionBiasResponse } from "@/lib/api";

// Advisory ES/MES overnight-bias card. Engine-derived (Saty + TPO + Corey),
// NOT a mirror of the ThinkOrSwim chart. No order controls by design.
const REFRESH_MS = 60_000;

function biasVariant(bias?: string): "bull" | "bear" | "neutral" {
  if (bias === "long") return "bull";
  if (bias === "short") return "bear";
  return "neutral";
}

function fmt(n: number | null | undefined): string {
  return typeof n === "number" ? n.toFixed(2) : "—";
}

function fmtPct(n: number | null | undefined): string {
  return typeof n === "number" ? `${(n * 100).toFixed(0)}%` : "—";
}

function fmtAtr(n: number | null | undefined): string {
  return typeof n === "number" ? `${n > 0 ? "+" : ""}${n.toFixed(2)} ATR` : "—";
}

function labelize(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ") : "—";
}

export function AuctionBiasCard({ symbol = "MES" }: { symbol?: string }) {
  const { data, error, isLoading } = useSWR<AuctionBiasResponse>(
    ["auction-bias", symbol],
    () => fetchAuctionBias(symbol),
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false }
  );

  const live = data?.available === true && data.provenance?.is_live === true;

  return (
    <Card className="border-2 border-slate-500/20 bg-slate-500/5 shadow-lg overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3 bg-slate-500/10">
        <div className="flex items-center gap-2">
          <Compass className="h-5 w-5 text-slate-400" />
          <CardTitle className="text-sm font-bold uppercase tracking-widest text-slate-100">
            {symbol} Auction Bias
          </CardTitle>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={live ? "live" : "static"}>{live ? "LIVE" : "STATIC"}</Badge>
          {data?.available && (
            <Badge variant={biasVariant(data.saty?.bias)}>
              {(data.saty?.bias ?? "neutral").toUpperCase()}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-4 text-sm">
        {isLoading && <p className="text-muted-foreground">Loading…</p>}

        {error && (
          <p className="text-bear">Failed to reach engine — {String(error)}</p>
        )}

        {data && data.available === false && (
          <p className="text-muted-foreground">
            No live market data ({data.error ?? "unavailable"}). Bias unavailable — the
            engine data provider is offline or not wired.
          </p>
        )}

        {data?.available && data.synthesis && (
          <div className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground">Last</span>
              <span className="font-mono">{fmt(data.price)}</span>
            </div>

            <div className="rounded-md border border-border/60 p-3 space-y-1">
              <div className="flex items-baseline justify-between">
                <span className="text-muted-foreground">Line in the sand</span>
                <span className="font-mono text-base font-bold">
                  {fmt(data.synthesis.line_in_sand)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Long above · short below ({data.synthesis.line_source})
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="flex flex-col">
                <span className="text-muted-foreground">Confirm long &gt;</span>
                <span className="font-mono text-bull">
                  {fmt(data.synthesis.confirm_long_above)}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-muted-foreground">Confirm short &lt;</span>
                <span className="font-mono text-bear">
                  {fmt(data.synthesis.confirm_short_below)}
                </span>
              </div>
            </div>

            <div className="rounded-md border border-border/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Saty ATR Pro context</p>
                {data.saty?.chase_risk && <Badge variant="warn">CHASE RISK</Badge>}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Displacement</span>
                  <span className="font-mono">{fmtAtr(data.saty?.atr_displacement)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Range used</span>
                  <span className="font-mono">{fmtPct(data.saty?.day_range_pct_of_atr)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Range state</span>
                  <span className="capitalize">{labelize(data.saty?.range_state)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Trigger state</span>
                  <span className="capitalize">{labelize(data.saty?.trigger_state)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Next up</span>
                  <span className="font-mono text-bull">{fmt(data.saty?.next_levels?.up)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Next down</span>
                  <span className="font-mono text-bear">{fmt(data.saty?.next_levels?.down)}</span>
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground">
                Context score: up {data.saty?.context_score?.up ?? 0} / down {data.saty?.context_score?.down ?? 0};
                neutral read-only map, not an execution signal.
              </p>
            </div>

            <div className="rounded-md bg-muted/40 p-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Lean</p>
              <p className="font-medium">{data.synthesis.lean}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {data.synthesis.overnight_recommendation}
              </p>
            </div>

            {data.caveats && data.caveats.length > 0 && (
              <ul className="space-y-1">
                {data.caveats.map((c) => (
                  <li key={c} className="flex items-start gap-1.5 text-xs text-warn">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            )}

            <p className="text-[10px] text-muted-foreground border-t border-border/40 pt-2">
              Engine-derived (Saty + TPO + Corey) — not a mirror of the TOS chart. Advisory
              only; no orders are placed from this card.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
