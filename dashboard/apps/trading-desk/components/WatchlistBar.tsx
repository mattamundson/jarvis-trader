"use client";

import React from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { PriceSnapshot, PriceSnapshotEntry, WatchlistItem } from "@/lib/api";
import { ProvenanceBadge } from "@/components/DataValue";
import {
  classifyProvenance,
  type DataEnvelope,
  type ProvenanceView,
} from "@/lib/provenance";

// ── Constants ──────────────────────────────────────────────────────────────
const POLL_MS = 10_000;
const WATCHLIST_SYMBOLS = "SPY,QQQ,IWM,VIX,MES,MNQ,MCL,MGC";
// Fallback freshness window when the engine entry omits stale_after_s.
const DEFAULT_STALE_AFTER_S = 60;

// ── Fetcher ────────────────────────────────────────────────────────────────
function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Provenance helpers ───────────────────────────────────────────────────────

/**
 * Ticking client clock (null on server / first render for hydration parity).
 * Lets a value age past its window downgrade LIVE -> STALE on screen.
 */
function useNowMs(): number | null {
  const [nowMs, setNowMs] = React.useState<number | null>(null);
  React.useEffect(() => {
    setNowMs(Date.now());
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return nowMs;
}

/** Map a raw price-snapshot entry to the canonical DataEnvelope shape. */
function toEnvelope(entry: PriceSnapshotEntry | undefined): DataEnvelope {
  return {
    value: entry?.last_price ?? null,
    source: entry?.source ?? "unavailable",
    as_of: entry?.as_of ?? null,
    is_live: entry?.is_live ?? false,
    stale_after_s: entry?.stale_after_s ?? DEFAULT_STALE_AFTER_S,
  };
}

// Most-degraded-wins ranking so the bar-level badge never claims LIVE while any
// priced symbol is served from a cached/delayed tier.
const STATUS_RANK: Record<ProvenanceView["status"], number> = {
  live: 3,
  stale: 2,
  static: 1,
  unavailable: 0,
};

function fmtAge(seconds: number | null): string {
  if (seconds == null) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h`;
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function formatPrice(price: number | null): string {
  if (price == null) return "—";
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

function statusDotClass(status: ProvenanceView["status"]): string {
  if (status === "live") return "bg-bull animate-pulse";
  if (status === "stale") return "bg-warn";
  return "bg-muted-foreground";
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface PriceChipProps {
  symbol: string;
  entry: PriceSnapshotEntry | undefined;
  view: ProvenanceView;
}

function PriceChip({ symbol, entry, view }: PriceChipProps) {
  const pct = entry?.change_pct ?? null;
  const price = entry?.last_price ?? null;
  const colorClass = changeColorClass(pct);
  const priceDisplay = price != null ? `$${formatPrice(price)}` : "—";
  const changeDisplay = pct != null ? `${formatChangePct(pct)} ${changeArrow(pct)}` : "";
  const age = view.ageSeconds != null ? fmtAge(view.ageSeconds) : "";
  // Provenance-aware label: source tier + age, so the chip is never a bare number.
  const provenanceLabel = [
    `source: ${view.source}`,
    view.status === "live" ? "LIVE" : view.status.toUpperCase(),
    age ? `${age} ago` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const ariaLabel = `${symbol}: ${priceDisplay} ${changeDisplay} — ${provenanceLabel}`;

  return (
    <div
      className="flex items-center gap-1.5 shrink-0 rounded-md border border-border bg-background/60 px-3 py-1.5 ring-offset-2 focus-within:ring-2 focus-within:ring-accent"
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
      title={provenanceLabel}
    >
      {/* Provenance status dot — honest per-symbol source/staleness */}
      {price != null && (
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(view.status)}`}
          aria-hidden="true"
        />
      )}

      {/* Symbol */}
      <span className="font-mono text-xs font-bold text-foreground tracking-wider">
        {symbol}
      </span>

      {/* Price */}
      <span className="font-mono text-xs tabular-nums text-foreground/90">
        {price != null ? `$${formatPrice(price)}` : "—"}
      </span>

      {/* Change */}
      {pct != null && (
        <span className={`font-mono text-xs tabular-nums font-semibold ${colorClass}`}>
          {formatChangePct(pct)} {changeArrow(pct)}
        </span>
      )}

      {/* Age since observed (as_of) */}
      {price != null && age && (
        <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
          {age}
        </span>
      )}
    </div>
  );
}

// ── MARKET CLOSED badge ────────────────────────────────────────────────────

function MarketClosedBadge() {
  return (
    <span
      className="shrink-0 rounded border border-warn/40 bg-warn/10 px-2 py-0.5 font-mono text-xs font-semibold text-warn tracking-widest"
      role="status"
      aria-label="Market is currently closed"
    >
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
  const nowMs = useNowMs();

  const { data: snapshot, error } = useSWR<PriceSnapshot>(
    `/prices/snapshot?symbols=${WATCHLIST_SYMBOLS}`,
    fetcher,
    { refreshInterval: POLL_MS }
  );

  const symbols = WATCHLIST_SYMBOLS.split(",");

  // Classify every symbol against its real source + freshness (not fetch recency).
  const views = symbols.map((sym) =>
    classifyProvenance(toEnvelope(snapshot?.[sym]), nowMs)
  );

  // Determine if market is closed: all priced entries are null.
  const priceEntries = snapshot ? Object.values(snapshot) : [];
  const allPricesNull =
    priceEntries.length > 0 && priceEntries.every((e) => e.last_price == null);
  const marketClosed = allPricesNull || (!!error && !snapshot);

  // Bar-level provenance: most-degraded of the priced symbols wins, so a single
  // cached (csv_cache / polygon) symbol keeps the strip from flashing green LIVE.
  const pricedViews = symbols
    .map((sym, i) => ({ view: views[i], hasPrice: snapshot?.[sym]?.last_price != null }))
    .filter((v) => v.hasPrice)
    .map((v) => v.view);
  const aggregateView =
    pricedViews.length > 0
      ? pricedViews.reduce((worst, v) =>
          STATUS_RANK[v.status] < STATUS_RANK[worst.status] ? v : worst
        )
      : null;

  const loading = !snapshot && !error;

  return (
    <div className="flex items-center gap-3 overflow-x-auto rounded-xl border border-border bg-card px-4 py-2.5 scrollbar-none">
      {/* Status indicators — leftmost */}
      <div className="flex items-center gap-2 shrink-0 mr-1">
        {aggregateView && !marketClosed && <ProvenanceBadge view={aggregateView} />}
        {marketClosed && <MarketClosedBadge />}
        {loading && !marketClosed && (
          <span className="font-mono text-xs text-muted-foreground tracking-widest">
            LOADING…
          </span>
        )}
      </div>

      {/* Thin divider */}
      <div className="h-5 w-px bg-border shrink-0" />

      {/* Price chips */}
      {symbols.map((sym, i) => (
        <PriceChip key={sym} symbol={sym} entry={snapshot?.[sym]} view={views[i]} />
      ))}

      {/* Fallback when engine is completely offline and no legacy items */}
      {error && !snapshot && items.length === 0 && (
        <p className="font-mono text-xs text-muted-foreground">
          Engine offline — start{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            uvicorn main:app
          </code>
        </p>
      )}
    </div>
  );
}
