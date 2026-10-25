"use client";

import { useEffect, useState } from "react";
import { PieChart, AlertTriangle } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * P&L Attribution — Mission Control.
 *
 * Breaks the headline realized-P&L number down into where it actually came from,
 * and reports the share that came from symbols that are still tradeable.
 *
 * WHY THIS MATTERS
 * ----------------
 * `PaperTradeAuditCard` shows +$4,426.57. That number is 90.5% MGC — a symbol
 * on DO_NOT_TRADE_SYMBOLS that can no longer be traded. The one authorised
 * instrument (MES) contributed $492.72. Without attribution the headline reads
 * as performance when it is largely history.
 *
 * Engine route: GET /analytics/pnl-attribution
 * Read-only — queries paper_trades directly, never routes orders.
 */

type Bucket = {
  bucket: string;
  trades: number;
  total_pnl: number | null;
  avg_pnl: number | null;
  wins: number;
  losses: number;
  win_rate: number | null;
};

type Attribution = {
  total_pnl: number;
  closed_trades: number;
  tradeable_pnl: number;
  blocked_pnl: number;
  tradeable_share_pct: number | null;
  do_not_trade_symbols: string[];
  by_symbol: Bucket[];
  by_strategy: Bucket[];
  field_coverage: Record<string, number>;
};

function fmtMoney(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function fmtPct(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : `${n.toFixed(1)}%`;
}

/** Worst-offender strategies (negative contributors), most negative first. */
function worstStrategies(rows: Bucket[], n = 3): Bucket[] {
  return rows.filter((r) => (r.total_pnl ?? 0) < 0).slice(-n).reverse();
}

export function PnLAttributionCard() {
  const [data, setData] = useState<Attribution | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await fetchEngine<Attribution>("/analytics/pnl-attribution");
        if (cancelled) return;
        setData(payload);
        setOffline(false);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "fetch failed";
        if (/(^|\D)(404|503)(\D|$)/.test(msg)) setOffline(true);
        else setError(msg);
      }
    }
    load();
    const interval = setInterval(load, POLL_INTERVAL.SLOW);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (offline) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <PieChart className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-foreground">P&L Attribution</h3>
          <Badge variant="bear" className="ml-auto">OFFLINE</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Attribution unavailable — /analytics/pnl-attribution returned no data.
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <PieChart className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-foreground">P&L Attribution</h3>
        </div>
        <p className="text-xs text-muted-foreground">Loading attribution…</p>
      </div>
    );
  }

  const share = data.tradeable_share_pct;
  const lowShare = share != null && share < 50;
  const blockedSet = new Set(data.do_not_trade_symbols.map((s) => s.toUpperCase()));
  const worst = worstStrategies(data.by_strategy);
  const ddSymbols = data.by_symbol.filter((r) => blockedSet.has(r.bucket.toUpperCase()));

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <PieChart className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">P&L Attribution</h3>
        <Badge
          variant={lowShare ? "warn" : "info"}
          className="ml-auto text-[10px]"
        >
          {fmtPct(share)} tradeable
        </Badge>
      </div>

      {/* Headline split — the single most important line on this card */}
      <div className="grid grid-cols-3 gap-2 text-[10px]">
        <div>
          <span className="text-muted-foreground">Total</span>
          <div className="font-mono text-foreground">{fmtMoney(data.total_pnl, 0)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Tradeable</span>
          <div className="font-mono text-bull">{fmtMoney(data.tradeable_pnl, 0)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Blocked</span>
          <div className="font-mono text-bear">{fmtMoney(data.blocked_pnl, 0)}</div>
        </div>
      </div>

      {/* Blocked-symbol warning */}
      {lowShare && ddSymbols.length > 0 && (
        <div className="rounded border border-warn/30 bg-warn/5 p-2 space-y-1">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="h-3 w-3 text-warn" />
            <span className="text-[10px] font-semibold text-warn">
              Headline is mostly history
            </span>
          </div>
          <p className="text-[10px] text-muted-foreground">
            {fmtPct(100 - (share ?? 0))} of realized P&L came from do-not-trade symbols:{" "}
            {ddSymbols.map((r) => r.bucket).join(", ")}.
          </p>
        </div>
      )}

      {/* By symbol */}
      <div className="border-t border-border pt-2">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
          By Symbol
        </span>
        <div className="mt-1 space-y-0.5">
          {data.by_symbol.slice(0, 6).map((r) => {
            const blocked = blockedSet.has(r.bucket.toUpperCase());
            return (
              <div key={r.bucket} className="flex items-center gap-2 text-[10px]">
                <span className={`font-mono w-12 ${blocked ? "text-muted-foreground" : "text-foreground"}`}>
                  {r.bucket}
                </span>
                <span className="text-muted-foreground w-8 text-right">{r.trades}</span>
                <span
                  className={`font-mono flex-1 text-right ${
                    (r.total_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"
                  }`}
                >
                  {fmtMoney(r.total_pnl, 0)}
                </span>
                {blocked && (
                  <Badge variant="neutral" className="text-[8px] px-1 py-0">
                    DNT
                  </Badge>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Worst strategies */}
      {worst.length > 0 && (
        <div className="border-t border-border pt-2">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
            Worst Strategies
          </span>
          <div className="mt-1 space-y-0.5">
            {worst.map((r) => (
              <div key={r.bucket} className="flex items-center gap-2 text-[10px]">
                <span className="font-mono text-muted-foreground flex-1 truncate">
                  {r.bucket}
                </span>
                <span className="text-muted-foreground w-8 text-right">{r.trades}</span>
                <span className="font-mono text-bear text-right">
                  {fmtMoney(r.total_pnl, 0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data coverage — never let absent data read as zero */}
      {data.field_coverage && (
        <div className="border-t border-border pt-2">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
            Attribution Coverage
          </span>
          <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[9px]">
            {Object.entries(data.field_coverage)
              .filter(([k]) => k !== "closed_trades")
              .map(([k, v]) => {
                const label = k.replace(/_pct$/, "").replace(/_/g, " ");
                const missing = v === 0;
                return (
                  <div key={k} className="flex justify-between">
                    <span className="text-muted-foreground truncate">{label}</span>
                    <span className={`font-mono ${missing ? "text-bear" : "text-foreground"}`}>
                      {v}%
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {error && (
        <p className="text-[10px] text-bear border-t border-border pt-2">{error}</p>
      )}

      <div className="text-[10px] text-muted-foreground border-t border-border pt-2 font-mono">
        /analytics/pnl-attribution · {data.closed_trades} closed
      </div>
    </div>
  );
}