"use client";

import { useEffect, useState } from "react";
import { Activity, Clock } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * TOS Live Quotes — Mission Control.
 *
 * Engine route: GET /prices/snapshot?symbols=SPY,QQQ,VIX
  * (thinkorswim RTD sits at Tier 0 of the engine's market-data waterfall, so
  * this reflects whatever tier actually served the quote rather than assuming
  * a single vendor).
  *
  * Paths handed to fetchEngine() are ENGINE-relative: lib/api.ts prepends
  * "/api/engine", so the browser request is
  *   /api/engine/prices/snapshot?symbols=SPY,QQQ,VIX
  * and app/api/engine/[...path]/route.ts forwards it to the engine as
  *   /prices/snapshot?symbols=SPY,QQQ,VIX
  * with the server-only X-API-Key injected.
 */

const SYMBOLS = ["SPY", "QQQ", "VIX"] as const;

type RawQuote = Record<string, unknown>;

interface QuoteRow {
  symbol: string;
  last: number | null;
  bid: number | null;
  ask: number | null;
  source: string | null;
  stale: boolean;
  error: string | null;
}

/** First finite number among `keys` (accepts numeric strings; ignores null/""). */
function pickNumber(src: RawQuote | null, keys: string[]): number | null {
  if (!src) return null;
  for (const key of keys) {
    const v = src[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string" && v.trim() !== "") {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

/** First non-empty string among `keys`. */
function pickString(src: RawQuote | null, keys: string[]): string | null {
  if (!src) return null;
  for (const key of keys) {
    const v = src[key];
    if (typeof v === "string" && v.trim() !== "") return v.trim();
  }
  return null;
}

function pickBoolean(src: RawQuote | null, keys: string[]): boolean {
  if (!src) return false;
  for (const key of keys) {
    const v = src[key];
    if (typeof v === "boolean") return v;
  }
  return false;
}

function normalize(symbol: string, raw: RawQuote | null): QuoteRow {
  return {
    symbol,
    last: pickNumber(raw, ["last", "last_price", "price", "close", "mark"]),
    bid: pickNumber(raw, ["bid", "bid_price", "best_bid"]),
    ask: pickNumber(raw, ["ask", "ask_price", "best_ask"]),
    source: pickString(raw, ["source", "data_source", "provider", "tier", "feed"]),
    // Explicit falseness only: absent provenance fields must not be presented
    // as stale (nor as fresh).
    stale: pickBoolean(raw, ["stale", "is_stale"]) || raw?.["is_live"] === false,
    error: null,
  };
}

function fmtPrice(n: number | null): string {
  return n == null ? "—" : n.toFixed(2);
}

/** Short, readable label for the engine's source/tier string. */
function sourceLabel(source: string | null): string {
  if (!source) return "N/A";
  const s = source.toLowerCase();
  if (s.includes("rtd") || s.includes("tos") || s.includes("thinkorswim")) return "TOS";
  if (s.includes("ibkr") || s === "ib" || s.includes("ib_gateway")) return "IBKR";
  if (s.includes("polygon")) return "POLY";
  if (s.includes("yahoo") || s.includes("yf")) return "YF";
  if (s.includes("cache")) return "CACHE";
  return source.toUpperCase().slice(0, 8);
}

type Variant = "bull" | "bear" | "warn" | "info" | "neutral";

function sourceVariant(row: QuoteRow): Variant {
  if (row.error) return "neutral";
  if (row.stale) return "warn";
  const s = (row.source ?? "").toLowerCase();
  if (s.includes("ibkr") || s === "ib" || s.includes("ib_gateway")) return "bull";
  if (s.includes("rtd") || s.includes("tos") || s.includes("thinkorswim")) return "info";
  if (s.includes("cache") || s.includes("polygon") || s.includes("yahoo") || s.includes("yf")) {
    return "warn";
  }
  return "neutral";
}

function isNotFound(message: string): boolean {
  return /(^|\D)404(\D|$)/.test(message);
}

function timeOf(ts: number | null): string {
  if (ts == null) return "—";
  return new Date(ts).toLocaleTimeString("en-US", { hour12: false });
}

export function TOSLiveQuotesCard() {
  const [rows, setRows] = useState<QuoteRow[]>([]);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // One call for all symbols: /prices/snapshot returns { SYMBOL: {...} }.
      let payload: Record<string, RawQuote> | null = null;
      let fetchError: string | null = null;
      try {
        payload = await fetchEngine<Record<string, RawQuote>>(
          `/prices/snapshot?symbols=${SYMBOLS.join(",")}`
        );
      } catch (e) {
        fetchError = e instanceof Error ? e.message : "fetch failed";
      }
      if (cancelled) return;

      const settled: QuoteRow[] = SYMBOLS.map((symbol) => {
        if (fetchError) {
          return { symbol, last: null, bid: null, ask: null, source: null, stale: false, error: fetchError };
        }
        const raw = payload?.[symbol] ?? null;
        return normalize(symbol, raw);
      });

      setRows(settled);
      setLoadedOnce(true);

      const anyQuote = settled.some((r) => r.last != null || r.bid != null || r.ask != null);
      const errors = settled.filter((r) => r.error).map((r) => r.error as string);

      if (anyQuote) {
        setOffline(false);
        setError(null);
        setUpdatedAt(Date.now());
      } else if (fetchError && isNotFound(fetchError)) {
        // Route absent on this engine build — report it as such, not as a
        // transient failure, and never substitute a placeholder price.
        setOffline(true);
        setError(null);
      } else if (errors.length > 0) {
        setOffline(false);
        setError(errors[0]);
      } else {
        setOffline(false);
        setError(null);
        setUpdatedAt(Date.now());
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.FAST);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (offline) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-foreground">TOS Live Quotes</h3>
          <Badge variant="bear" className="ml-auto">
            OFFLINE
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Quotes offline — the engine has no{" "}
          <span className="font-mono text-[10px]">/prices/snapshot</span>{" "}
          route on this build.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">TOS Live Quotes</h3>
        <Badge variant="info" className="ml-auto">
          {POLL_INTERVAL.FAST / 1000}s
        </Badge>
      </div>

      {/* Compact quote grid: symbol / last / bid / ask / source */}
      <div className="grid grid-cols-5 gap-x-3 gap-y-1.5 items-center">
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Sym</span>
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground text-right">Last</span>
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground text-right">Bid</span>
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground text-right">Ask</span>
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground text-right">Src</span>

        {rows.map((row) => (
          <div key={row.symbol} className="col-span-5 grid grid-cols-5 gap-x-3 items-center">
            <span className="text-xs font-mono font-semibold text-foreground">{row.symbol}</span>
            <span
              className={`text-xs font-mono text-right ${
                row.error ? "text-muted-foreground" : "text-foreground"
              }`}
            >
              {fmtPrice(row.last)}
            </span>
            <span className="text-xs font-mono text-right text-muted-foreground">{fmtPrice(row.bid)}</span>
            <span className="text-xs font-mono text-right text-muted-foreground">{fmtPrice(row.ask)}</span>
            <span className="flex justify-end">
              <Badge variant={sourceVariant(row)} className="text-[10px] px-1.5 py-0">
                {row.error ? "N/A" : sourceLabel(row.source)}
              </Badge>
            </span>
          </div>
        ))}

        {rows.length === 0 && (
          <p className="col-span-5 text-xs text-muted-foreground">Loading quotes…</p>
        )}
      </div>

      {error && (
        <p className="text-xs text-muted-foreground border-t border-border pt-2">
          Quote fetch failed: {error}
        </p>
      )}

      <div className="flex items-center gap-1 text-[10px] text-muted-foreground border-t border-border pt-2">
        <Clock className="h-3 w-3" />
        <span className="font-mono">
          {loadedOnce && updatedAt != null ? `updated ${timeOf(updatedAt)}` : "awaiting first quote"}
        </span>
        <span className="ml-auto font-mono">/prices/snapshot</span>
      </div>
    </div>
  );
}
