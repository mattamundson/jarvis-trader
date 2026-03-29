"use client";

import React, { useRef } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { PriceSnapshot, PriceSnapshotEntry, WatchlistItem } from "@/lib/api";

// ── Constants ──────────────────────────────────────────────────────────────
const POLL_MS = 10_000;
const STALE_THRESHOLD_MS = 30_000;
const WATCHLIST_SYMBOLS = "SPY,QQQ,IWM,VIX,MES,MNQ,MCL,MGC";

// ── Fetcher ────────────────────────────────────────────────────────────────
function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function formatPrice(price: number | null, symbol: string): string {
  if (price == null) return "—";
  // Futures have large numbers, format accordingly
  if (price >= 1000) {
    return price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return price.toFixed(2);
}

function formatChangePct(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

function changeArrow(pct: number | null): string {
  if (pct == null || Math.abs(pct) < 0.00005) return "◆";
  return pct > 0 ? "▲" : "▼";
}

function changeColorClass(pct: number | null): string {
  if (pct == null || Math.abs(pct) < 0.00005) return "text-muted-foreground";
  return pct > 0 ? "text-bull" : "text-bear";
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface PriceChipProps {
  symbol: string;
  entry: PriceSnapshotEntry | undefined;
}

function PriceChip({ symbol, entry }: PriceChipProps) {
  const pct = entry?.change_pct ?? null;
  const price = entry?.last_price ?? null;
  const colorClass = changeColorClass(pct);

  return (
    <div className="flex items-center gap-1.5 shrink-0 rounded-md border border-border bg-background/60 px-3 py-1.5">
      {/* Symbol */}
      <span className="font-mono text-xs font-bold text-foreground tracking-wider">
        {symbol}
      </span>

      {/* Price */}
      <span className="font-mono text-xs tabular-nums text-foreground/90">
        {price != null ? `$${formatPrice(price, symbol)}` : "—"}
      </span>

      {/* Change */}
      {pct != null && (
        <span className={`font-mono text-xs tabular-nums font-semibold ${colorClass}`}>
          {formatChangePct(pct)} {changeArrow(pct)}
        </span>
      )}
    </div>
  );
}

// ── Pulsing LIVE dot ────────────────────────────────────────────────────────

function LiveDot({ isFresh }: { isFresh: boolean }) {
  if (!isFresh) return null;
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-bull" />
      </span>
      <span className="font-mono text-[10px] font-bold text-bull tracking-widest">LIVE</span>
    </div>
  );
}

// ── MARKET CLOSED badge ────────────────────────────────────────────────────

function MarketClosedBadge() {
  return (
    <span className="shrink-0 rounded border border-warn/40 bg-warn/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-warn tracking-widest">
      MARKET CLOSED
    </span>
  );
}

// ── Main WatchlistBar ──────────────────────────────────────────────────────

interface WatchlistBarProps {
  /** Legacy prop — still accepted but prices now come from /prices/snapshot */
  items?: WatchlistItem[];
}

export function WatchlistBar({ items = [] }: WatchlistBarProps) {
  const lastSuccessfulFetch = useRef<number | null>(null);

  const { data: snapshot, error } = useSWR<PriceSnapshot>(
    `/prices/snapshot?symbols=${WATCHLIST_SYMBOLS}`,
    fetcher,
    {
      refreshInterval: POLL_MS,
      onSuccess: () => {
        lastSuccessfulFetch.current = Date.now();
      },
    }
  );

  // Determine freshness
  const now = Date.now();
  const msSinceFetch = lastSuccessfulFetch.current ? now - lastSuccessfulFetch.current : Infinity;
  const isFresh = msSinceFetch < STALE_THRESHOLD_MS && !!snapshot && !error;

  // Determine if market is closed: all prices null or data very stale
  const priceEntries = snapshot ? Object.values(snapshot) : [];
  const allPricesNull = priceEntries.length > 0 && priceEntries.every((e) => e.last_price == null);
  const isStale = msSinceFetch > 60_000 || (!!error && !snapshot);
  const marketClosed = allPricesNull || (!!error && !snapshot);

  // Build the ordered symbol list to display
  const symbols = WATCHLIST_SYMBOLS.split(",");

  return (
    <div className="flex items-center gap-3 overflow-x-auto rounded-xl border border-border bg-card px-4 py-2.5 scrollbar-none">
      {/* Status indicators — leftmost */}
      <div className="flex items-center gap-2 shrink-0 mr-1">
        <LiveDot isFresh={isFresh} />
        {marketClosed && <MarketClosedBadge />}
        {!isFresh && !marketClosed && !error && (
          <span className="font-mono text-[10px] text-muted-foreground tracking-widest">
            LOADING…
          </span>
        )}
      </div>

      {/* Thin divider */}
      <div className="h-5 w-px bg-border shrink-0" />

      {/* Price chips */}
      {symbols.map((sym) => (
        <PriceChip key={sym} symbol={sym} entry={snapshot?.[sym]} />
      ))}

      {/* Fallback when engine is completely offline and no legacy items */}
      {error && !snapshot && items.length === 0 && (
        <p className="font-mono text-xs text-muted-foreground">
          Engine offline — start{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
            uvicorn main:app --port 8010
          </code>
        </p>
      )}
    </div>
  );
}
