"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { DiscordIntelligenceStatus } from "@/lib/api";

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function SignalPill({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${
        active
          ? "bg-bull/15 text-bull border border-bull/30"
          : "bg-muted/40 text-muted-foreground border border-border"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${active ? "bg-bull animate-pulse" : "bg-muted-foreground/40"}`}
      />
      {active ? "ACTIVE" : "INACTIVE"}
    </span>
  );
}

function AlignmentPill({ alignment }: { alignment: number }) {
  if (alignment > 0.5) {
    return (
      <span className="inline-flex items-center rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider bg-bull/15 text-bull border border-bull/30">
        ALIGNED
      </span>
    );
  }
  if (alignment < -0.5) {
    return (
      <span className="inline-flex items-center rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider bg-bear/15 text-bear border border-bear/30">
        OPPOSED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider bg-warn/15 text-warn border border-warn/30">
      NEUTRAL
    </span>
  );
}

function SymbolCard({
  symbol,
  features,
}: {
  symbol: string;
  features: DiscordIntelligenceStatus["symbols"][string];
}) {
  const active = (features.discord_signal_active ?? 0) > 0.5;
  const winRate = features.discord_win_rate_context ?? 0;
  const proxEntry = features.discord_proximity_entry ?? 0;
  const proxTarget = features.discord_proximity_target ?? 0;
  const alignment = features.discord_alignment ?? 0;

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-bold text-foreground">{symbol}</span>
        <SignalPill active={active} />
      </div>

      {active && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-muted-foreground">Win Rate</span>
            <span className="font-mono text-[10px] font-semibold text-foreground tabular-nums">
              {(winRate * 100).toFixed(0)}%
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-muted-foreground">Entry Prox</span>
            <span className="font-mono text-[10px] font-semibold tabular-nums text-foreground">
              {proxEntry >= 0 ? "+" : ""}{proxEntry.toFixed(2)} ATR
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-muted-foreground">Target Prox</span>
            <span className="font-mono text-[10px] font-semibold tabular-nums text-foreground">
              {proxTarget.toFixed(2)} ATR
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-muted-foreground">Alignment</span>
            <AlignmentPill alignment={alignment} />
          </div>
        </div>
      )}

      {!active && (
        <p className="font-mono text-[10px] text-muted-foreground/60">No active signal</p>
      )}
    </div>
  );
}

export function DiscordIntelligenceWidget() {
  const { data, error, isLoading } = useSWR<DiscordIntelligenceStatus>(
    "/discord/intelligence",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Discord Intelligence
        </p>
        {data?.last_updated && (
          <span className="font-mono text-[9px] text-muted-foreground/60">
            {new Date(data.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>

      {isLoading && (
        <p className="font-mono text-[10px] text-muted-foreground/60 animate-pulse">Loading...</p>
      )}

      {error && !isLoading && (
        <p className="font-mono text-[10px] text-bear/70">Unavailable</p>
      )}

      {data && !error && (
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(data.symbols).map(([sym, features]) => (
            <SymbolCard key={sym} symbol={sym} features={features} />
          ))}
        </div>
      )}
    </div>
  );
}
