"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 60_000; // poll every 60 seconds

// ── Types ─────────────────────────────────────────────────────────────────────

interface RegimeLayer {
  status: "active" | "stub";
  value?: number | null;
  classification?: string;
  timeframes_aligned?: number | null;
  signal?: string;
  direction?: string;
  above_average?: boolean | null;
}

interface RegimeResponse {
  timestamp: string;
  regime: "BULLISH" | "BEARISH" | "NEUTRAL" | "UNKNOWN";
  confidence: number;
  layers: {
    vix: RegimeLayer;
    mtf: RegimeLayer;
    stc: RegimeLayer;
    ema_trend: RegimeLayer;
    volume: RegimeLayer;
  };
  note?: string;
  trade_filter: "pass" | "block" | "unknown";
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function formatTime(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// ── Regime metadata ───────────────────────────────────────────────────────────

interface RegimeMeta {
  label: string;
  colorClass: string;
  badgeBg: string;
  badgeBorder: string;
  dot: string;
}

const REGIME_META: Record<string, RegimeMeta> = {
  BULLISH: {
    label: "Bullish",
    colorClass: "text-bull",
    badgeBg: "bg-bull/10",
    badgeBorder: "border-bull/30",
    dot: "bg-bull",
  },
  BEARISH: {
    label: "Bearish",
    colorClass: "text-bear",
    badgeBg: "bg-bear/10",
    badgeBorder: "border-bear/30",
    dot: "bg-bear",
  },
  NEUTRAL: {
    label: "Neutral",
    colorClass: "text-warn",
    badgeBg: "bg-warn/10",
    badgeBorder: "border-warn/30",
    dot: "bg-warn",
  },
  UNKNOWN: {
    label: "Unknown",
    colorClass: "text-muted-foreground",
    badgeBg: "bg-muted/10",
    badgeBorder: "border-border",
    dot: "bg-muted-foreground/40",
  },
};

function getRegimeMeta(regime: string): RegimeMeta {
  return REGIME_META[regime] ?? REGIME_META["UNKNOWN"];
}

// ── Layer dot ─────────────────────────────────────────────────────────────────
//
// A layer dot is:
//   green  — status "active" and value/signal indicates aligned
//   yellow — status "stub" (not yet connected to live data)
//   red    — status "active" and value/signal indicates misaligned
//
function resolveLayerState(
  layer: RegimeLayer | undefined,
  regime: string
): "active_aligned" | "active_misaligned" | "stub" {
  if (!layer) return "stub";
  if (layer.status === "stub") return "stub";

  // Layer is active — determine alignment from regime
  if (regime === "BULLISH") return "active_aligned";
  if (regime === "BEARISH") return "active_misaligned";
  return "stub";
}

function LayerDot({ label, state }: { label: string; state: "active_aligned" | "active_misaligned" | "stub" }) {
  // stub layers render muted gray (inactive), never bg-warn — a yellow dot
  // reads as a live caution signal and is exactly the "stub looks live" lie.
  const dotColor =
    state === "active_aligned"
      ? "bg-bull"
      : state === "active_misaligned"
      ? "bg-bear"
      : "bg-muted-foreground/40";
  const textColor =
    state === "active_aligned"
      ? "text-bull"
      : state === "active_misaligned"
      ? "text-bear"
      : "text-muted-foreground/60";
  const title =
    state === "stub"
      ? `${label}: not wired yet (Phase 3 — live data feed needed)`
      : state === "active_aligned"
      ? `${label}: active, aligned`
      : `${label}: active, misaligned`;

  return (
    <div className="flex flex-col items-center gap-1" title={title}>
      <div className={`h-2.5 w-2.5 rounded-full ${dotColor}`} />
      <span className={`font-mono text-[9px] font-semibold tracking-wide ${textColor}`}>
        {label}
      </span>
    </div>
  );
}

// ── Trade filter badge ────────────────────────────────────────────────────────

function TradeFilterBadge({ filter }: { filter: "pass" | "block" | "unknown" }) {
  if (filter === "pass") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-bull/30 bg-bull/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-widest text-bull uppercase">
        PASS
      </span>
    );
  }
  if (filter === "block") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-bear/30 bg-bear/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-widest text-bear uppercase">
        BLOCK
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-border bg-muted/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-widest text-muted-foreground uppercase">
      UNKNOWN
    </span>
  );
}

// ── RegimeDisplay component ───────────────────────────────────────────────────

export function RegimeDisplay() {
  const {
    data: regime,
    isLoading,
    error,
  } = useSWR<RegimeResponse>("/analytics/regime", fetcher, {
    refreshInterval: REFRESH_MS,
  });

  const meta = getRegimeMeta(regime?.regime ?? "UNKNOWN");

  // Determine per-layer dot states
  const regimeStr = regime?.regime ?? "UNKNOWN";
  const layers = regime?.layers;
  const vixState = resolveLayerState(layers?.vix, regimeStr);
  const mtfState = resolveLayerState(layers?.mtf, regimeStr);
  const stcState = resolveLayerState(layers?.stc, regimeStr);
  const emaState = resolveLayerState(layers?.ema_trend, regimeStr);
  const volState = resolveLayerState(layers?.volume, regimeStr);

  const allStubs =
    layers?.vix?.status === "stub" &&
    layers?.mtf?.status === "stub" &&
    layers?.stc?.status === "stub" &&
    layers?.ema_trend?.status === "stub" &&
    layers?.volume?.status === "stub";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between gap-2">
          <span>Market Regime</span>
          {!isLoading && !error && regime && (
            <span className="text-xs text-muted-foreground font-normal">
              {formatTime(regime.timestamp)}
            </span>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent>
        {isLoading && (
          <div className="flex items-center gap-2 py-4">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <span className="text-xs text-muted-foreground">Loading regime…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-xs text-bear py-4 text-center">
            Unable to fetch regime data — engine may be offline.
          </p>
        )}

        {!isLoading && !error && regime && (
          <div className="space-y-3">
            {/* Regime label + trade filter */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className={`h-3 w-3 rounded-full ${meta.dot} flex-shrink-0`} />
                <span className={`text-base font-bold leading-tight ${meta.colorClass}`}>
                  {meta.label}
                </span>
                <span
                  className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-widest uppercase ${
                    allStubs
                      ? "border-amber-500/50 bg-amber-500/10 text-amber-400"
                      : `${meta.badgeBg} ${meta.badgeBorder} ${meta.colorClass}`
                  }`}
                  title={
                    allStubs
                      ? "5-layer filter is not wired to live data — this regime is reference-only, not a live signal"
                      : undefined
                  }
                >
                  {allStubs ? "NOT LIVE" : `${(regime.confidence * 100).toFixed(0)}%`}
                </span>
              </div>
              <div className="flex flex-col items-end gap-0.5">
                <span className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider">
                  Filter
                </span>
                <TradeFilterBadge filter={regime.trade_filter} />
              </div>
            </div>

            {/* Loud not-live disclaimer when the 5-layer filter is unwired */}
            {allStubs && (
              <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] font-medium leading-snug text-amber-400">
                Reference only — all 5 regime layers are stubs (not wired to live
                data). Do not treat this regime or confidence as a live signal.
              </p>
            )}

            {/* 5-layer indicators */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                  5-Layer Filter
                </p>
                {allStubs && (
                  <span className="rounded border border-muted-foreground/30 bg-muted/20 px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-widest text-muted-foreground/70">
                    Not wired · Phase 3
                  </span>
                )}
              </div>
              <div className="flex items-end gap-3">
                <LayerDot label="VIX" state={vixState} />
                <LayerDot label="MTF" state={mtfState} />
                <LayerDot label="STC" state={stcState} />
                <LayerDot label="EMA" state={emaState} />
                <LayerDot label="VOL" state={volState} />
              </div>
            </div>

            {/* VIX detail */}
            {layers?.vix?.value != null && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">VIX</span>
                <span className="font-mono tabular-nums">
                  {layers.vix.value.toFixed(1)}{" "}
                  <span className="text-muted-foreground text-[10px]">
                    ({layers.vix.classification})
                  </span>
                </span>
              </div>
            )}

          </div>
        )}
      </CardContent>
    </Card>
  );
}
