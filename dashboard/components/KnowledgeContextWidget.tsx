"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchDiscordBriefing } from "@/lib/api";
import type { BriefingResponse, KnowledgeContextHit } from "@/lib/api";

/**
 * Curated-knowledge panel — surfaces the advisory gbrain hits attached to the
 * enriched Discord briefing (the Voyage vault brain). ADVISORY context only:
 * this is the same `knowledge_context` the agents see, never a gate/sizing input.
 *
 * The rerank-tier badge is the observability signal for the silent
 * Voyage->local degradation class: voyage = primary (good), local = fallback
 * (Voyage key/endpoint unavailable — quality degraded), off = no rerank ran.
 */

function TierBadge({ tier }: { tier?: string | null }) {
  const t = (tier ?? "").toLowerCase();
  const style =
    t === "voyage"
      ? "bg-bull/15 text-bull border-bull/30"
      : t === "local"
        ? "bg-warn/15 text-warn border-warn/30"
        : "bg-muted/40 text-muted-foreground border-border";
  const label = t === "voyage" ? "VOYAGE" : t === "local" ? "LOCAL (fallback)" : "OFF";
  return (
    <span
      title={
        t === "local"
          ? "Voyage reranker unavailable — degraded to local cross-encoder"
          : t === "off"
            ? "No reranker ran (identity order)"
            : "Voyage rerank-2.5 (primary)"
      }
      className={`inline-flex items-center rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider border ${style}`}
    >
      {label}
    </span>
  );
}

function ScorePill({ score }: { score?: number | null }) {
  if (score == null) return null;
  // Both tiers are 0..1 now; color by relevance band.
  const s = score;
  const tone =
    s >= 0.5
      ? "text-bull"
      : s >= 0.3
        ? "text-foreground"
        : "text-muted-foreground";
  return (
    <span className={`font-mono text-[10px] font-semibold tabular-nums ${tone}`}>
      {s.toFixed(2)}
    </span>
  );
}

function HitRow({ hit }: { hit: KnowledgeContextHit }) {
  const snippet = (hit.content ?? "").replace(/\s+/g, " ").trim().slice(0, 140);
  return (
    <div className="rounded-lg border border-border bg-card/50 p-2.5 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] font-bold text-foreground truncate" title={hit.slug}>
          {hit.title || hit.slug}
        </span>
        <ScorePill score={hit.rerank_score} />
      </div>
      <p className="font-mono text-[9px] text-muted-foreground/70 truncate" title={hit.slug}>
        {hit.slug}
      </p>
      {snippet && (
        <p className="font-mono text-[10px] leading-snug text-muted-foreground line-clamp-2">
          {snippet}
        </p>
      )}
    </div>
  );
}

export function KnowledgeContextWidget({ symbol = "MES" }: { symbol?: string }) {
  const { data, error, isLoading } = useSWR<BriefingResponse>(
    ["/discord/briefing", symbol, "enriched"],
    () => fetchDiscordBriefing(symbol, { enriched: true }),
    { refreshInterval: POLL_INTERVAL.FIVE_MINUTES, shouldRetryOnError: false }
  );

  const hits = data?.knowledge_context ?? [];

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Curated Knowledge
          <span className="ml-1.5 font-mono text-[9px] normal-case text-muted-foreground/50">
            {symbol}
          </span>
        </p>
        {data?.knowledge_context_tier && <TierBadge tier={data.knowledge_context_tier} />}
      </div>

      {isLoading && (
        <p className="font-mono text-[10px] text-muted-foreground/60 animate-pulse">Loading...</p>
      )}

      {error && !isLoading && (
        <p className="font-mono text-[10px] text-bear/70">Brain unavailable</p>
      )}

      {data && !error && hits.length === 0 && (
        <p className="font-mono text-[10px] text-muted-foreground/60">No curated hits</p>
      )}

      {data && !error && hits.length > 0 && (
        <div className="space-y-2">
          {hits.map((h, i) => (
            <HitRow key={`${h.slug}-${i}`} hit={h} />
          ))}
        </div>
      )}

      <p className="font-mono text-[9px] text-muted-foreground/40 leading-tight">
        Advisory context only — never a gate/sizing input.
      </p>
    </div>
  );
}
