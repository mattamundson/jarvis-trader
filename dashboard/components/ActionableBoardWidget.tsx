"use client";

import useSWR from "swr";
import { Crosshair } from "lucide-react";
import {
  fetchActionableBoard,
  type ActionableBoardResponse,
  type ActionableItem,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ResultLabel } from "@/components/ResultLabel";

const REFRESH_MS = 60_000;

// Status chip styling + one-line meaning (amo-arbitrage actionable-board
// vocabulary). Derived server-side so every surface agrees.
const STATUS_META: Record<string, { variant: "bull" | "bear" | "warn" | "info" | "neutral"; hint: string }> = {
  triggerable: { variant: "warn", hint: "Price is at the entry zone right now (within 0.25 ATR of entry)." },
  triggered: { variant: "info", hint: "Price has moved past entry toward the target." },
  awaiting_entry: { variant: "neutral", hint: "Price has not reached the entry level yet." },
  target_reached: { variant: "bull", hint: "Price touched the T1 target." },
  invalidated: { variant: "bear", hint: "Price breached the stop — the setup is dead." },
  expired: { variant: "neutral", hint: "Decision is older than the freshness window." },
  unknown: { variant: "neutral", hint: "No live price available — status honestly unknown." },
};

function fmtNum(v: number | null, digits = 2): string {
  return v != null ? v.toFixed(digits) : "—";
}

function ItemCard({ it }: { it: ActionableItem }) {
  const meta = STATUS_META[it.status] ?? STATUS_META.unknown;
  const dead = it.status === "invalidated" || it.status === "expired";
  return (
    <div
      className={`rounded-lg border border-border bg-card/50 p-3 space-y-1.5 ${
        dead ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-sm font-semibold text-foreground">{it.symbol}</span>
          <Badge variant={it.direction === "short" ? "bear" : "bull"}>{it.direction}</Badge>
          <span title={meta.hint}>
            <Badge variant={meta.variant} className="cursor-help">
              {it.status.replace(/_/g, " ")}
            </Badge>
          </span>
          {it.approval_status === "pending" && <Badge variant="warn">needs approval</Badge>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {it.confidence != null && (
            <span className="text-[11px] font-mono text-muted-foreground">
              conf {(it.confidence * 100).toFixed(0)}%
            </span>
          )}
          <ResultLabel kind="signal" />
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-[11px] font-mono text-muted-foreground">
        <span>
          entry <span className="text-foreground">{fmtNum(it.entry_price)}</span>
        </span>
        <span>
          stop <span className="text-foreground">{fmtNum(it.stop_loss)}</span>
        </span>
        <span>
          T1 <span className="text-foreground">{fmtNum(it.target_1)}</span>
        </span>
        <span>
          last <span className="text-foreground">{fmtNum(it.latest_price)}</span>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-muted-foreground">
        {it.distance_pct != null && (
          <span title="Favorable-signed distance from the latest price to the entry level. Positive = price still has to travel to entry.">
            to entry {fmtNum(it.distance_pct, 3)}%
            {it.distance_atr != null && <> · {fmtNum(it.distance_atr)} ATR</>}
          </span>
        )}
        {it.planned_rr != null && <span>planned RR {fmtNum(it.planned_rr, 1)}</span>}
        {it.current_r != null && (
          <span className={it.current_r > 0 ? "text-bull" : it.current_r < 0 ? "text-bear" : ""}>
            current R {it.current_r > 0 ? "+" : ""}
            {fmtNum(it.current_r)}
          </span>
        )}
        {it.age_days != null && <span>{it.age_days}d old</span>}
        {it.timeframe && <span>{it.timeframe}</span>}
      </div>
    </div>
  );
}

/**
 * Actionable-Now board over the pipeline's recent directional decisions:
 * status chip + distance-to-entry + R-multiples, derived server-side from the
 * latest cached price (GET /pipeline/actionable). Display-only — approval and
 * execution stay in the human-gated flow below/elsewhere on the page.
 */
export function ActionableBoardWidget() {
  const { data, error } = useSWR<ActionableBoardResponse>(
    "/pipeline/actionable",
    fetchActionableBoard,
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">Actionable Now</span>
        </div>
        <span className="text-[10px] text-muted-foreground">
          derived from latest price · display only
        </span>
      </div>

      {error ? (
        <p className="text-xs text-muted-foreground">
          Actionable board unreachable (engine offline or endpoint not deployed).
        </p>
      ) : !data ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading board…</p>
      ) : !data.available ? (
        <p className="text-xs text-muted-foreground">
          Board unavailable{data.note ? ` — ${data.note}` : ""}. Not a claim that
          there are no opportunities.
        </p>
      ) : data.items.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No recent directional decisions — nothing actionable right now.
        </p>
      ) : (
        <div className="space-y-2">
          {data.items.map((it) => (
            <ItemCard key={`${it.symbol}-${it.direction}-${it.approval_id ?? ""}`} it={it} />
          ))}
        </div>
      )}
    </div>
  );
}
