"use client";

import { useEffect, useState } from "react";
import { Crosshair, Clock } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Trade Recommendations — Mission Control.
 *
 * Engine route: GET /pipeline/status
 * (routers/pipeline_router.py -> { available, sdk_available, last_run,
 *   decision_count }; `last_run` is the newest entry in the engine's in-memory
 *   decision ring buffer).
 *
 * Paths handed to fetchEngine() are ENGINE-relative: lib/api.ts prepends
 * "/api/engine", so the browser request is /api/engine/pipeline/status and
 * app/api/engine/[...path]/route.ts forwards it to the engine as
 * /pipeline/status with the server-only X-API-Key. The engine origin is never
 * hardcoded here.
 *
 * The route is absent on some engine builds; a 404 renders the explicit
 * "Recommendations offline" state. Levels (entry/stop/target) render as "—"
 * when the payload does not carry them — they are never inferred or invented.
 */

type RawRec = Record<string, unknown>;

interface PipelineStatusResponse {
  available?: boolean;
  sdk_available?: boolean;
  last_run?: RawRec | null;
  decision_count?: number;
  // Tolerated aliases (older/newer engine shapes) — resolved in pickRecommendation.
  recommendation?: RawRec | null;
  latest?: RawRec | null;
  recommendations?: RawRec[] | null;
  [key: string]: unknown;
}

interface Recommendation {
  symbol: string | null;
  direction: string | null;
  confidence: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  timeframe: string | null;
  createdAt: string | null;
}

function isRecord(v: unknown): v is RawRec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** The newest recommendation from whichever field this engine build populates. */
function pickRecommendation(res: PipelineStatusResponse): RawRec | null {
  if (isRecord(res.recommendation)) return res.recommendation;
  if (Array.isArray(res.recommendations) && isRecord(res.recommendations[0])) {
    return res.recommendations[0];
  }
  if (isRecord(res.latest)) return res.latest;
  if (isRecord(res.last_run)) return res.last_run;
  return null;
}

function pickNumber(src: RawRec | null, keys: string[]): number | null {
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

function pickString(src: RawRec | null, keys: string[]): string | null {
  if (!src) return null;
  for (const key of keys) {
    const v = src[key];
    if (typeof v === "string" && v.trim() !== "") return v.trim();
  }
  return null;
}

function normalizeRec(raw: RawRec | null): Recommendation | null {
  if (!raw) return null;
  const confidenceRaw = pickNumber(raw, ["confidence", "confidence_score", "score"]);
  return {
    symbol: pickString(raw, ["symbol", "ticker", "instrument"]),
    direction: pickString(raw, ["direction", "action", "side", "signal_action", "signal"]),
    // Engine confidences are 0..1; a 0..100 payload is normalized to a fraction
    // so one formatter renders both honestly.
    confidence: confidenceRaw == null ? null : confidenceRaw <= 1 ? confidenceRaw : confidenceRaw / 100,
    entry: pickNumber(raw, ["entry", "entry_price", "limit_price", "price", "planned_entry"]),
    stop: pickNumber(raw, ["stop", "stop_loss", "stop_price", "stop_level"]),
    target: pickNumber(raw, ["target", "target_1", "take_profit", "target_price", "target_level"]),
    timeframe: pickString(raw, ["timeframe", "interval", "tf"]),
    createdAt: pickString(raw, ["created_at", "timestamp", "date", "as_of"]),
  };
}

type Variant = "bull" | "bear" | "warn" | "info" | "neutral";

function directionMeta(direction: string | null): { label: string; variant: Variant } {
  const d = (direction ?? "").toLowerCase();
  if (d === "long" || d === "buy" || d === "bull" || d === "bullish") {
    return { label: "LONG", variant: "bull" };
  }
  if (d === "short" || d === "sell" || d === "bear" || d === "bearish") {
    return { label: "SHORT", variant: "bear" };
  }
  if (d === "hold" || d === "none" || d === "flat" || d === "wait" || d === "no_trade") {
    return { label: d === "no_trade" ? "NO TRADE" : d.toUpperCase(), variant: "neutral" };
  }
  if (d === "") return { label: "—", variant: "neutral" };
  return { label: d.toUpperCase(), variant: "neutral" };
}

function fmtPrice(n: number | null): string {
  return n == null ? "—" : n.toFixed(2);
}

function fmtConfidence(n: number | null): string {
  return n == null ? "—" : `${(n * 100).toFixed(0)}%`;
}

/** Planned reward:risk, only when all three levels are present. */
function plannedRr(rec: Recommendation): string {
  if (rec.entry == null || rec.stop == null || rec.target == null) return "—";
  const risk = Math.abs(rec.entry - rec.stop);
  const reward = Math.abs(rec.target - rec.entry);
  if (risk === 0) return "—";
  return `${(reward / risk).toFixed(2)}R`;
}

function isNotFound(message: string): boolean {
  return /(^|\D)404(\D|$)/.test(message);
}

function shortTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso;
  return t.toLocaleString("en-US", { hour12: false });
}

export function TradeRecommendationsCard() {
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [meta, setMeta] = useState<{ available: boolean; decisionCount: number | null } | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetchEngine<PipelineStatusResponse>("/pipeline/status");
        if (cancelled) return;
        setRec(normalizeRec(pickRecommendation(res)));
        setMeta({
          available: res.available === true,
          decisionCount: typeof res.decision_count === "number" ? res.decision_count : null,
        });
        setOffline(false);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        const message = e instanceof Error ? e.message : "Failed to load";
        // A 404 is a durable "route not on this build" fact, not a blip.
        setOffline(isNotFound(message));
        setError(isNotFound(message) ? null : message);
      } finally {
        if (!cancelled) setLoadedOnce(true);
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.SLOW);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (offline) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-foreground">Trade Recommendations</h3>
          <Badge variant="bear" className="ml-auto">
            OFFLINE
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">Recommendations offline</p>
        <p className="text-[10px] font-mono text-muted-foreground">
          engine route /pipeline/status returned 404 on this build
        </p>
      </div>
    );
  }

  const dir = directionMeta(rec?.direction ?? null);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Crosshair className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">Trade Recommendations</h3>
        {rec && (
          <Badge variant={dir.variant} className="ml-auto">
            {dir.label}
          </Badge>
        )}
      </div>

      {error && (
        <p className="text-xs text-muted-foreground">Recommendations unavailable: {error}</p>
      )}

      {!error && rec && (
        <>
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-mono font-semibold text-foreground">
              {rec.symbol ?? "—"}
            </span>
            <span className="text-xs text-muted-foreground">
              confidence <span className="font-mono text-foreground">{fmtConfidence(rec.confidence)}</span>
              {rec.timeframe ? <span className="ml-2 font-mono">{rec.timeframe}</span> : null}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-3 border-t border-border pt-2">
            <div className="space-y-0.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Entry</div>
              <div className="text-xs font-mono text-foreground">{fmtPrice(rec.entry)}</div>
            </div>
            <div className="space-y-0.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Stop</div>
              <div className="text-xs font-mono text-bear">{fmtPrice(rec.stop)}</div>
            </div>
            <div className="space-y-0.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Target</div>
              <div className="text-xs font-mono text-bull">{fmtPrice(rec.target)}</div>
            </div>
          </div>

          {rec.entry == null && rec.stop == null && rec.target == null && (
            <p className="text-[10px] text-muted-foreground">
              This engine build&apos;s pipeline status omits trade levels — shown as — rather than
              inferred.
            </p>
          )}
        </>
      )}

      {!error && !rec && loadedOnce && (
        <p className="text-xs text-muted-foreground">
          No recommendation yet
          {meta?.decisionCount != null ? (
            <span className="font-mono"> · {meta.decisionCount} decision(s) logged</span>
          ) : null}
          {meta && !meta.available ? <span className="font-mono"> · pipeline unavailable</span> : null}
        </p>
      )}

      {!loadedOnce && <p className="text-xs text-muted-foreground">Loading recommendation…</p>}

      <div className="flex items-center gap-1 text-[10px] text-muted-foreground border-t border-border pt-2">
        <Clock className="h-3 w-3" />
        <span className="font-mono">{rec?.createdAt ? shortTime(rec.createdAt) : "no timestamp"}</span>
        <span className="ml-auto font-mono">R:R {rec ? plannedRr(rec) : "—"}</span>
      </div>
    </div>
  );
}
