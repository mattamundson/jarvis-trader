"use client";

import { useEffect, useState } from "react";
import { Activity, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * TOS Indicator Panel — Mission Control.
 *
 * Renders the derived indicator set that mirrors Matt's TOS /ES chart:
 *   ATR(14) · Keltner Channels (20, 3.5) · 5/15/30-min S/R · day-range gauge
 *
 * Engine route: GET /tos/indicators?symbols=...
 *
 * PROVENANCE — read this before trusting a number:
 * These values are **derived in-process** from the live thinkorswim RTD price
 * stream, NOT read from TOS ThinkScript studies. TOS's RTD server only answers
 * native quote topics (LAST/BID/ASK/CLOSE); study outputs like
 * ATRTrailingStopLE or AA_CoreyTscorev2 are not queryable by name. The payload
 * therefore carries `source: "derived"` and this card labels it as such rather
 * than implying TOS computed it.
 *
 * A null is rendered as an em-dash and never as a zero: the ATR is genuinely
 * unknown until enough 1-minute bars have closed.
 */

const SYMBOLS = ["SPY", "QQQ", "VIX", "MES"] as const;

type Variant = "bull" | "bear" | "warn" | "info" | "neutral";

interface SRLevel {
  tf_minutes?: number;
  top?: number | null;
  bottom?: number | null;
}

interface SymbolIndicators {
  symbol?: string;
  last_price?: number | null;
  source?: string | null;
  price_source?: string | null;
  atr?: { value?: number | null; period?: number; bars_used?: number } | null;
  keltner?: {
    upper?: number | null;
    mid?: number | null;
    lower?: number | null;
    ema_period?: number;
    atr_multiplier?: number;
  } | null;
  sr_levels?: SRLevel[];
  day_range?: {
    day_high?: number | null;
    day_low?: number | null;
    day_range?: number | null;
    atr?: number | null;
    range_pct?: number | null;
  } | null;
  as_of?: number | null;
}

interface IndicatorsResponse {
  source?: string;
  price_source?: string;
  symbols?: Record<string, SymbolIndicators>;
}

function fmt(n: number | null | undefined, digits = 2): string {
  return n == null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

/** Compression gauge → badge variant. Null (no ATR yet) must stay neutral. */
function rangeVariant(pct: number | null | undefined): Variant {
  if (pct == null || !Number.isFinite(pct)) return "neutral";
  if (pct >= 80) return "warn"; // expanded day — late to chase
  if (pct <= 50) return "info"; // compressed — breakout setup territory
  return "neutral";
}

function rangeLabel(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return "no ATR yet";
  if (pct >= 80) return "expanded";
  if (pct <= 50) return "compressed";
  return "normal";
}

/** Where is spot relative to the Keltner band? */
function keltnerPosition(row: SymbolIndicators): {
  label: string;
  variant: Variant;
  Icon: typeof TrendingUp;
} {
  const last = row.last_price;
  const k = row.keltner;
  if (last == null || !k || k.upper == null || k.lower == null) {
    return { label: "n/a", variant: "neutral", Icon: Minus };
  }
  if (last >= k.upper) return { label: "above upper", variant: "bull", Icon: TrendingUp };
  if (last <= k.lower) return { label: "below lower", variant: "bear", Icon: TrendingDown };
  return { label: "inside band", variant: "neutral", Icon: Minus };
}

export function TOSIndicatorCard() {
  const [data, setData] = useState<Record<string, SymbolIndicators>>({});
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await fetchEngine<IndicatorsResponse>(
          `/tos/indicators?symbols=${SYMBOLS.join(",")}`
        );
        if (cancelled) return;
        setData(payload?.symbols ?? {});
        setOffline(false);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        const message = e instanceof Error ? e.message : "fetch failed";
        // 503 = connector not injected; 404 = route absent on this build.
        if (/(^|\D)(404|503)(\D|$)/.test(message)) {
          setOffline(true);
          setError(null);
        } else {
          setError(message);
        }
      } finally {
        if (!cancelled) setLoadedOnce(true);
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.NORMAL);
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
          <h3 className="text-sm font-semibold text-foreground">TOS Indicators</h3>
          <Badge variant="bear" className="ml-auto">
            OFFLINE
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Indicator engine offline — the engine has no{" "}
          <span className="font-mono text-[10px]">/tos/indicators</span> route, or the
          thinkorswim RTD connector is not injected.
        </p>
      </div>
    );
  }

  const rows = SYMBOLS.map((s) => [s, data[s] ?? {}] as const);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">TOS Indicators</h3>
        <Badge variant="neutral" className="ml-auto text-[10px]">
          derived
        </Badge>
      </div>

      <div className="space-y-3">
        {rows.map(([sym, row]) => {
          const kp = keltnerPosition(row);
          const atrReady = row.atr?.value != null;
          const pct = row.day_range?.range_pct ?? null;
          return (
            <div key={sym} className="border-t border-border pt-2 first:border-t-0 first:pt-0">
              {/* Header row: symbol · price · keltner position */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-semibold text-foreground w-12">
                  {sym}
                </span>
                <span className="text-xs font-mono text-foreground">
                  {fmt(row.last_price)}
                </span>
                <span className="ml-auto flex items-center gap-1">
                  <kp.Icon className="h-3 w-3 text-muted-foreground" />
                  <Badge variant={kp.variant} className="text-[10px] px-1.5 py-0">
                    {kp.label}
                  </Badge>
                </span>
              </div>

              {/* Metric row: ATR · Keltner band · day range */}
              <div className="mt-1 grid grid-cols-3 gap-x-3 text-[10px]">
                <div>
                  <span className="text-muted-foreground uppercase tracking-wide">ATR</span>
                  <div className="font-mono text-foreground">
                    {atrReady ? fmt(row.atr?.value) : "warming"}
                    {atrReady && row.atr?.bars_used ? (
                      <span className="text-muted-foreground">
                        {" "}
                        ({row.atr.bars_used}b)
                      </span>
                    ) : null}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground uppercase tracking-wide">Keltner</span>
                  <div className="font-mono text-foreground">
                    {fmt(row.keltner?.lower)} / {fmt(row.keltner?.upper)}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground uppercase tracking-wide">
                    Day Range
                  </span>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-foreground">
                      {pct == null ? "—" : `${pct}%`}
                    </span>
                    <Badge variant={rangeVariant(pct)} className="text-[9px] px-1 py-0">
                      {rangeLabel(pct)}
                    </Badge>
                  </div>
                </div>
              </div>

              {/* S/R row */}
              {row.sr_levels && row.sr_levels.length > 0 ? (
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
                  {row.sr_levels.map((sr) => (
                    <span key={sr.tf_minutes} className="font-mono">
                      {sr.tf_minutes}m{" "}
                      <span className="text-bear">{fmt(sr.top)}</span>
                      {" / "}
                      <span className="text-bull">{fmt(sr.bottom)}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {error && (
        <p className="text-xs text-muted-foreground border-t border-border pt-2">
          Indicator fetch failed: {error}
        </p>
      )}

      <div className="flex items-center gap-1 text-[10px] text-muted-foreground border-t border-border pt-2">
        <span className="font-mono">
          {loadedOnce ? `updated ${new Date().toLocaleTimeString("en-US", { hour12: false })}` : "loading"}
        </span>
        <span className="ml-auto font-mono">/tos/indicators</span>
      </div>
    </div>
  );
}