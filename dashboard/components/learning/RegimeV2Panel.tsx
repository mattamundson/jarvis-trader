"use client";

import useSWR from "swr";
import { fetchRegimeV2, type RegimeV2Response } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

// Active + halted paper instruments per engine/CLAUDE.md "Active Instruments".
const SYMBOLS = ["MES", "MGC", "MCL", "MNQ"] as const;

type RegimeResult = RegimeV2Response | { symbol: string; error: true };

function regimeBadgeVariant(regime: string): "bull" | "bear" | "warn" | "neutral" {
  switch (regime) {
    case "TREND":   return "bull";
    case "CRISIS":  return "bear";
    case "VOLATILE": return "warn";
    case "MEANREV":
    case "RANGE":   return "neutral";
    default:        return "neutral";
  }
}

async function fetchAllRegimes(): Promise<RegimeResult[]> {
  return Promise.all(
    SYMBOLS.map((s) =>
      fetchRegimeV2(s).catch(() => ({ symbol: s, error: true as const }))
    )
  );
}

function RegimeRow({ result }: { result: RegimeResult }) {
  const isError = "error" in result;
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors">
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-xs font-semibold text-foreground">{result.symbol}</span>
        {isError ? (
          <Badge variant="static">unavailable</Badge>
        ) : (
          <Badge variant={regimeBadgeVariant(result.regime)}>{result.regime}</Badge>
        )}
      </div>
      {!isError && result.description && (
        <p className="font-mono text-[10px] text-muted-foreground/60">{result.description}</p>
      )}
      {!isError && result.note && (
        <p className="font-mono text-[10px] text-muted-foreground/40 italic">{result.note}</p>
      )}
    </div>
  );
}

export function RegimeV2Panel() {
  const { data, isLoading, error } = useSWR("regime-v2-all", fetchAllRegimes, {
    refreshInterval: REFRESH_MS,
  });

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-4 space-y-1">
        <div className="flex items-center gap-2">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Regime State (Live Pipeline Classifier)
          </p>
          <Badge variant={error ? "static" : "live"}>{error ? "static" : "live"}</Badge>
        </div>
        <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
          RegimeClassifierV2 (backtest/regime_classifier.py) — the same classifier
          engine/agents/pipeline.py uses to route strategies. Deterministic
          rule-based thresholds only: no probability vector, and no
          ground-truth accuracy validation exists for this classifier yet.
        </p>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
            Loading regime state…
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(data ?? []).map((r) => (
            <RegimeRow key={r.symbol} result={r} />
          ))}
        </div>
      )}
    </div>
  );
}
