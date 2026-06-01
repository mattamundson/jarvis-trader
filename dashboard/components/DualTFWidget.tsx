"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { DualTFResponse, DualTFSymbol } from "@/lib/api";

const REFRESH_MS = 60_000; // 60 s

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function DirectionBadge({ dir }: { dir: "long" | "short" | "neutral" }) {
  if (dir === "long")
    return (
      <span className="rounded px-1.5 py-0.5 text-[10px] font-bold bg-green-500/15 text-green-400 leading-none">
        LONG
      </span>
    );
  if (dir === "short")
    return (
      <span className="rounded px-1.5 py-0.5 text-[10px] font-bold bg-red-500/15 text-red-400 leading-none">
        SHORT
      </span>
    );
  return (
    <span className="rounded px-1.5 py-0.5 text-[10px] font-bold bg-white/5 text-muted-foreground leading-none">
      HOLD
    </span>
  );
}

function STCBar({ val, os, ob }: { val: number; os: number; ob: number }) {
  const pct = Math.max(0, Math.min(100, val));
  const color =
    val <= os
      ? "bg-green-500"
      : val >= ob
      ? "bg-red-500"
      : val >= 50
      ? "bg-yellow-500/70"
      : "bg-sky-500/70";
  return (
    <div className="relative h-1 w-full rounded-full bg-white/10 overflow-hidden">
      <div className={`absolute inset-y-0 left-0 ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function SymbolRow({ row }: { row: DualTFSymbol }) {
  const confirmed = row.confirmed;
  return (
    <div className="rounded-lg border border-border/60 bg-background/60 px-3 py-2.5 space-y-2">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-bold text-foreground">{row.symbol}</span>
        {confirmed ? (
          <span
            className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-wider ${
              row.direction === "long"
                ? "bg-green-500/20 text-green-400 border border-green-500/30"
                : "bg-red-500/20 text-red-400 border border-red-500/30"
            }`}
          >
            CONFIRMED {row.direction.toUpperCase()}
          </span>
        ) : (
          <span className="rounded px-2 py-0.5 text-[10px] font-bold tracking-wider bg-white/5 text-muted-foreground border border-border/40">
            UNCONFIRMED
          </span>
        )}
      </div>

      {/* 1h row */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground font-mono w-8">1h</span>
          {row.tf_1h ? (
            <>
              <span className="tabular-nums text-foreground/80">{row.tf_1h.stc_val.toFixed(1)}</span>
              <DirectionBadge dir={row.tf_1h.direction} />
            </>
          ) : (
            <span className="text-muted-foreground/50 text-[10px]">no data</span>
          )}
        </div>
        {row.tf_1h && (
          <STCBar val={row.tf_1h.stc_val} os={row.stc_os} ob={row.stc_ob} />
        )}
      </div>

      {/* 15m row */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground font-mono w-8">15m</span>
          {row.tf_15m ? (
            <>
              <span className="tabular-nums text-foreground/80">{row.tf_15m.stc_val.toFixed(1)}</span>
              <DirectionBadge dir={row.tf_15m.direction} />
            </>
          ) : (
            <span className="text-muted-foreground/50 text-[10px]">no data</span>
          )}
        </div>
        {row.tf_15m && (
          <STCBar val={row.tf_15m.stc_val} os={row.stc_os} ob={row.stc_ob} />
        )}
      </div>

      {row.error && (
        <p className="text-[10px] text-red-400/70 truncate">{row.error}</p>
      )}
    </div>
  );
}

export function DualTFWidget({ symbols = "MCL,MNQ,MES" }: { symbols?: string }) {
  const { data, error, isLoading } = useSWR<DualTFResponse>(
    `/analytics/dual-tf-status?symbols=${symbols}`,
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Dual-TF Confirmation
        </p>
        {data?.timestamp && (
          <span className="text-[10px] text-muted-foreground/50 tabular-nums">
            {new Date(data.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </span>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {["MCL", "MNQ", "MES"].map((s) => (
            <div key={s} className="h-20 rounded-lg bg-white/5 animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400/70">Engine unavailable — retrying…</p>
      )}

      {data && !isLoading && (
        <div className="space-y-2">
          {(data.symbols ?? []).map((row) => (
            <SymbolRow key={row.symbol} row={row} />
          ))}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground/40 leading-tight">
        Per-instrument OS/OB thresholds — confirmed when 1h &amp; 15m agree on direction
      </p>
    </div>
  );
}
