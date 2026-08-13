"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import React, { useState, useCallback } from "react";
import useSWR from "swr";
import { Activity, Cpu, Radio, Shield, ShieldOff, Zap } from "lucide-react";
import { BookmarkThemesPanel } from "@/components/BookmarkThemesPanel";
import { BookmarkFeedPanel } from "@/components/BookmarkFeedPanel";
import { QuantStatsPanel } from "@/components/QuantStatsPanel";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { RiskAttributionPanel } from "@/components/RiskAttributionPanel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AskJarvis, type AskJarvisSend } from "@/components/AskJarvis";
import {
  fetchEngine,
  fetchJarvisAsk,
  fetchDiscordBriefing,
  fetchBookmarksRecent,
  type HealthResponse,
  type BriefingResponse,
  type BookmarkRow,
} from "@/lib/api";
import {
  usePipelineSocket,
  type PipelineWsEvent,
  type VerdictEvent,
} from "@/lib/pipeline_ws";
import { DEFAULT_BRIEFING_SYMBOLS } from "@/lib/approvedSymbols";

// ── Constants ─────────────────────────────────────────────────────────────────

const HERO_REFRESH_MS = 30_000;
const BRIEFING_REFRESH_MS = 5 * 60_000;
const BOOKMARKS_REFRESH_MS = 5 * 60_000;

// ── Helpers ───────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function uptimeLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function titleForRow(row: BookmarkRow): string {
  if (row.embed_title) return row.embed_title;
  try {
    const u = new URL(row.url);
    const path = u.pathname.replace(/\/$/, "");
    return (u.hostname.replace(/^www\./, "") + (path || "/")).slice(0, 72);
  } catch {
    return row.url.slice(0, 72);
  }
}

function biasBadgeVariant(bias: unknown): BadgeVariant {
  if (!bias) return "neutral";
  // corey_bias can be an object (engine returns structured dict) — coerce to string
  const b = (typeof bias === "string" ? bias : JSON.stringify(bias)).toLowerCase();
  if (b.includes("bull") || b.includes("long")) return "bull";
  if (b.includes("bear") || b.includes("short")) return "bear";
  if (b.includes("neutral")) return "neutral";
  return "info";
}

// ── StatusPill ─────────────────────────────────────────────────────────────────

function StatusPill({
  label,
  ok,
  unknown,
}: {
  label: string;
  ok: boolean | null | undefined;
  unknown?: boolean;
}) {
  const variant: BadgeVariant = unknown ? "neutral" : ok ? "bull" : "bear";
  return (
    <Badge variant={variant} className="text-[10px] font-mono tracking-wider">
      {label}
    </Badge>
  );
}

// ── HeroStrip ──────────────────────────────────────────────────────────────────

function HeroStrip() {
  const { data: health, error } = useSWR<HealthResponse>(
    "/health",
    (path: string) => fetchEngine<HealthResponse>(path),
    { refreshInterval: HERO_REFRESH_MS }
  );

  // Live verdict flash state — symbol → flash active
  const [flashedSymbols, setFlashedSymbols] = useState<Record<string, boolean>>({});

  const handleWsEvent = useCallback((event: PipelineWsEvent) => {
    if (event.type !== "verdict") return;
    const { symbol } = event as VerdictEvent;
    setFlashedSymbols((prev) => ({ ...prev, [symbol]: true }));
    // Clear flash after 2 s
    setTimeout(() => {
      setFlashedSymbols((prev) => {
        const next = { ...prev };
        delete next[symbol];
        return next;
      });
    }, 2000);
  }, []);

  // Subscribe — gracefully degrades to SWR polling if WS fails
  usePipelineSocket(handleWsEvent);

  const isOnline = !error && !!health;
  const engineOk = health?.status === "ok" || health?.status === "healthy";

  const anyFlash = Object.keys(flashedSymbols).length > 0;
  const flashLabel = anyFlash
    ? Object.keys(flashedSymbols).join(" ")
    : null;

  return (
    <div
      className={[
        "w-full rounded-xl border border-zinc-800 px-5 py-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 backdrop-blur transition-colors duration-700",
        anyFlash ? "bg-emerald-500/10" : "bg-zinc-950/80",
      ].join(" ")}
    >
      {/* Left — identity */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
          <Activity className="h-5 w-5 text-emerald-400" />
        </div>
        <div>
          <h1 className="font-bold text-zinc-100 tracking-tight leading-none">
            JARVIS COMMAND CENTER
          </h1>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {flashLabel ? (
              <span className="text-emerald-400 font-mono">
                verdict received: {flashLabel}
              </span>
            ) : (
              "Stark Mode — unified live view"
            )}
          </p>
        </div>
      </div>

      {/* Center — pulse metrics */}
      {health && (
        <div className="flex items-center gap-4 text-xs font-mono text-zinc-400">
          <span>
            <span className="text-zinc-600">uptime </span>
            <span className="text-zinc-200">{uptimeLabel(health.uptime_seconds ?? 0)}</span>
          </span>
          {health.kill_switch_active && (
            <span className="flex items-center gap-1 text-rose-400">
              <ShieldOff className="h-3.5 w-3.5" />
              KILL ACTIVE
            </span>
          )}
          {!health.kill_switch_active && engineOk && (
            <span className="flex items-center gap-1 text-emerald-400">
              <Shield className="h-3.5 w-3.5" />
              CLEAR
            </span>
          )}
        </div>
      )}

      {/* Right — status pills */}
      <div className="flex items-center gap-2 flex-wrap">
        <StatusPill label="ENGINE" ok={isOnline && engineOk} unknown={!isOnline} />
        <StatusPill
          label="IBKR"
          ok={health?.ibkr_connected ?? null}
          unknown={!health}
        />
        <StatusPill
          label="TV MCP"
          ok={health?.tradingview_mcp_healthy ?? null}
          unknown={!health}
        />
        <StatusPill
          label="LLM"
          ok={health?.llm_path_healthy ?? null}
          unknown={!health}
        />
        {health?.kill_switch_active != null && (
          <Badge
            variant={health.kill_switch_active ? "bear" : "neutral"}
            className="text-[10px] font-mono"
          >
            {health.kill_switch_active ? "KILL ON" : "KILL OFF"}
          </Badge>
        )}
      </div>
    </div>
  );
}

// ── RegimePulsePanel ───────────────────────────────────────────────────────────

function RegimePulsePanel() {
  const SYMBOLS = ["MES", "MNQ", "MCL", "MGC"] as const;

  const fetchRegime = useCallback((symbol: string) => {
    return fetchEngine<{ current_regime?: string; regime?: string; [key: string]: unknown }>(
      `/analytics/regime/${symbol}`
    );
  }, []);

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <Radio className="h-4 w-4" /> Regime Pulse
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-4 space-y-2">
        {SYMBOLS.map((sym) => (
          <RegimeRow key={sym} symbol={sym} fetcher={fetchRegime} />
        ))}
      </CardContent>
    </Card>
  );
}

function RegimeRow({
  symbol,
  fetcher,
}: {
  symbol: string;
  fetcher: (s: string) => Promise<{ current_regime?: string; regime?: string; [key: string]: unknown }>;
}) {
  const { data, error, isLoading } = useSWR(
    `/analytics/regime/${symbol}`,
    () => fetcher(symbol),
    { refreshInterval: POLL_INTERVAL.MINUTE, shouldRetryOnError: false }
  );

  const regime = data?.current_regime ?? data?.regime ?? null;

  function regimeVariant(r: string | null): BadgeVariant {
    if (!r) return "neutral";
    const lower = r.toLowerCase();
    if (lower.includes("trend") || lower.includes("bull")) return "bull";
    if (lower.includes("bear") || lower.includes("crash")) return "bear";
    if (lower.includes("range") || lower.includes("chop")) return "warn";
    return "info";
  }

  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-xs font-semibold text-zinc-300">{symbol}</span>
      {isLoading ? (
        <div className="h-4 w-16 animate-pulse rounded bg-zinc-800" />
      ) : error || !regime ? (
        <span className="font-mono text-[10px] text-zinc-600">—</span>
      ) : (
        <Badge variant={regimeVariant(regime)} className="text-[10px] font-mono">
          {regime}
        </Badge>
      )}
    </div>
  );
}

// ── DiscordBriefingPanel ───────────────────────────────────────────────────────

const BRIEFING_SYMBOLS = DEFAULT_BRIEFING_SYMBOLS;

function DiscordBriefingPanel() {
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <Zap className="h-4 w-4" /> Discord Briefing
        </CardTitle>
        <p className="text-[11px] text-zinc-500">Corey auction-theory commentary. 5-min cache.</p>
      </CardHeader>
      <CardContent className="pb-4 space-y-3">
        {BRIEFING_SYMBOLS.map((sym) => (
          <BriefingCard key={sym} symbol={sym} />
        ))}
      </CardContent>
    </Card>
  );
}

function BriefingCard({ symbol }: { symbol: string }) {
  const { data, error, isLoading } = useSWR<BriefingResponse>(
    `/discord/briefing?symbol=${symbol}`,
    () => fetchDiscordBriefing(symbol),
    { refreshInterval: BRIEFING_REFRESH_MS, shouldRetryOnError: false }
  );

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        <div className="h-3 w-12 animate-pulse rounded bg-zinc-800" />
        <div className="h-8 animate-pulse rounded bg-zinc-800/80" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2.5">
        <span className="font-mono text-xs font-semibold text-zinc-400">{symbol}</span>
        <p className="text-[10px] text-rose-400 mt-1">Briefing unavailable</p>
      </div>
    );
  }

  const ibl = data?.ib_levels;
  const sig = data?.recent_signal;

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2.5 space-y-2">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-bold text-zinc-200">{symbol}</span>
        {data?.corey_bias && (() => {
          // Engine returns corey_bias as either a string or a structured object
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const cb = data.corey_bias as any;
          const label: string = typeof cb === "string" ? cb : (cb?.directional_bias ?? "—");
          return (
            <Badge variant={biasBadgeVariant(cb)} className="text-[10px] font-mono">
              {label}
            </Badge>
          );
        })()}
      </div>

      {/* Headline */}
      {data?.headline ? (
        <p className="text-[11px] text-zinc-300 leading-relaxed line-clamp-2">
          {data.headline}
        </p>
      ) : (
        <p className="text-[11px] text-zinc-600 italic">No headline available</p>
      )}

      {/* IB levels + signal row */}
      <div className="flex items-center gap-3 text-[10px] font-mono text-zinc-500">
        {ibl && (ibl.high != null || ibl.low != null) && (
          <span>
            IB{" "}
            <span className="text-emerald-400">{ibl.high ?? "—"}</span>
            {" / "}
            <span className="text-rose-400">{ibl.low ?? "—"}</span>
          </span>
        )}
        {sig?.direction && (
          <Badge
            variant={biasBadgeVariant(sig.direction)}
            className="text-[10px] font-mono"
          >
            {sig.direction}
            {sig.confidence != null && ` ${Math.round(Number(sig.confidence) * 100)}%`}
          </Badge>
        )}
        {sig?.timestamp && (
          <span className="ml-auto text-zinc-600">{relativeTime(String(sig.timestamp))}</span>
        )}
      </div>
    </div>
  );
}

// ── ActionQueuePanel ───────────────────────────────────────────────────────────

function ActionQueuePanel() {
  const { data, error, isLoading } = useSWR(
    "/discord/bookmarks/recent?hours=72&limit=15",
    () => fetchBookmarksRecent({ hours: 72, limit: 15 }),
    { refreshInterval: BOOKMARKS_REFRESH_MS, shouldRetryOnError: false }
  );

  const rows: BookmarkRow[] = data?.data ?? [];

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <Cpu className="h-4 w-4" /> Action Queue
          </CardTitle>
          {rows.length > 0 && (
            <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px]">
              {rows.length} · 72h
            </Badge>
          )}
        </div>
        <p className="text-[11px] text-zinc-500">Recent Discord signals — compact view.</p>
      </CardHeader>
      <CardContent className="pb-3">
        {isLoading && (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-9 animate-pulse rounded bg-zinc-800/80" />
            ))}
          </div>
        )}
        {error && (
          <p className="text-xs text-rose-400">Queue unavailable — engine offline?</p>
        )}
        {!isLoading && !error && rows.length === 0 && (
          <p className="text-xs text-zinc-500 italic">No bookmarks in the last 72h.</p>
        )}
        {!isLoading && !error && rows.length > 0 && (
          <div className="space-y-1 max-h-80 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
            {rows.map((row, idx) => (
              <ActionQueueRow key={`${row.url}-${idx}`} row={row} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ActionQueueRow({ row }: { row: BookmarkRow }) {
  const title = titleForRow(row);
  const domainShort = row.domain
    ? row.domain.replace(/^www\./, "").slice(0, 18)
    : null;

  return (
    <a
      href={row.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-start gap-2 rounded border border-zinc-800/50 bg-zinc-900/30 px-2.5 py-1.5 hover:bg-zinc-800/60 transition-colors group"
    >
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-zinc-200 leading-snug line-clamp-1 group-hover:text-white transition-colors">
          {title}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          {domainShort && (
            <span className="font-mono text-[9px] text-zinc-600 bg-zinc-800/60 px-1 rounded">
              {domainShort}
            </span>
          )}
          <span className="font-mono text-[9px] text-zinc-700">
            {relativeTime(row.posted_at)}
          </span>
        </div>
      </div>
    </a>
  );
}

// ── AskJarvisPanel ─────────────────────────────────────────────────────────────
// Thin trading-engine wiring over the shared, canonical <AskJarvis> console. The
// backend transport is POST /jarvis/ask (verified live: engine/routers/jarvis_router.py).

function AskJarvisPanel() {
  const send = useCallback<AskJarvisSend>(async (q, { onText, onMeta }) => {
    const res = await fetchJarvisAsk(q);
    onText(res.answer);
    onMeta?.({
      sources: res.sources,
      actions: res.actions_taken,
      intent: res.intent,
      elapsedMs: res.elapsed_ms,
    });
  }, []);

  return (
    <AskJarvis
      send={send}
      title="Ask JARVIS"
      subtitle="Natural-language query to the engine's reasoning pipeline."
      placeholder="What is MES doing right now?"
      emptyHint="Ask JARVIS anything about the market, positions, or pipeline."
    />
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function JarvisCommandPage() {
  return (
    <div className="min-h-screen bg-background px-4 py-4 sm:px-6">
      {/* Hero strip */}
      <HeroStrip />

      {/* 3-column grid */}
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Column 1 — Decision state */}
        <div className="space-y-4">
          <RegimePulsePanel />
          <BookmarkThemesPanel />
          <BookmarkFeedPanel />
        </div>

        {/* Column 2 — Market intelligence */}
        <div className="space-y-4">
          <WidgetErrorBoundary name="Tearsheet">
            <QuantStatsPanel />
          </WidgetErrorBoundary>
          <RiskAttributionPanel />
          <DiscordBriefingPanel />
        </div>

        {/* Column 3 — Action queue */}
        <div className="space-y-4">
          <ActionQueuePanel />
          <AskJarvisPanel />
        </div>
      </div>
    </div>
  );
}
