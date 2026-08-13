"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchMacroRegime, type MacroRegime } from "@/lib/api";

// Advisory only — this state biases the futures LLM context solely when the
// ENABLE_MACRO_TREND_BIAS feature flag is on. It never routes capital and never
// overrides the CRISIS/VOLATILE hard-block. Derived from the X-bookmark trend
// edges (weekly Supertrend + monthly momentum) applied to SPY as an SPX proxy.

function stateStyle(state: MacroRegime["state"]): { bg: string; border: string; color: string; label: string } {
  switch (state) {
    case "RISK_ON":
      return { bg: "rgba(21,128,61,0.15)", border: "#15803d", color: "#4ade80", label: "RISK-ON" };
    case "RISK_OFF":
      return { bg: "rgba(185,28,28,0.14)", border: "#b91c1c", color: "#f87171", label: "RISK-OFF" };
    case "NEUTRAL":
      return { bg: "rgba(202,138,4,0.12)", border: "#ca8a04", color: "#facc15", label: "NEUTRAL" };
    default:
      return { bg: "rgba(120,120,120,0.10)", border: "#6b7280", color: "#9ca3af", label: "UNKNOWN" };
  }
}

/**
 * Macro trend regime badge — the market-wide SPX trend state consumed as an
 * advisory bias by the futures pipeline (GET /macro/regime). Compact card
 * suitable for the dashboard grid alongside the bookmark/research panels.
 */
export function MacroRegimeBadge() {
  const { data, error, isLoading } = useSWR<MacroRegime>(
    "macro-regime",
    fetchMacroRegime,
    { refreshInterval: POLL_INTERVAL.FIVE_MINUTES }
  );

  const s = stateStyle(data?.state ?? "UNKNOWN");

  return (
    <div className="border border-border rounded-lg p-4 bg-card flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-mono text-sm font-bold text-foreground">Macro Trend Regime</h2>
        {data && (
          <span
            className="font-mono text-[11px] font-bold shrink-0 rounded px-2 py-0.5"
            style={{ backgroundColor: s.bg, border: `1px solid ${s.border}`, color: s.color }}
          >
            {s.label}
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-muted-foreground">Loading macro regime…</p>}
      {error && <p className="text-xs text-destructive">Error loading macro regime</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md px-2 py-1.5 bg-card/60 border border-border flex flex-col gap-0.5">
              <span className="font-mono text-[10px] text-muted-foreground">Weekly Supertrend</span>
              <span className="font-mono text-sm font-semibold text-foreground">
                {data.weekly_trend ?? "—"}
              </span>
            </div>
            <div className="rounded-md px-2 py-1.5 bg-card/60 border border-border flex flex-col gap-0.5">
              <span className="font-mono text-[10px] text-muted-foreground">Monthly 12mo Mom.</span>
              <span className="font-mono text-sm font-semibold text-foreground">
                {data.monthly_momentum ?? "—"}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between font-mono text-[10px] text-muted-foreground">
            <span>SPY {data.spy_close ?? "—"}</span>
            <span>as of {data.asof ?? "—"}</span>
          </div>

          {data.bias_line ? (
            <p className="font-mono text-[11px] text-muted-foreground leading-snug">{data.bias_line}</p>
          ) : (
            <p className="font-mono text-[11px] text-muted-foreground/70 leading-snug">
              No directional bias (inert — baseline context unchanged).
            </p>
          )}

          <p className="font-mono text-[10px] text-muted-foreground/70">
            Advisory · flag-gated (ENABLE_MACRO_TREND_BIAS) · never routes capital.
          </p>
        </>
      )}
    </div>
  );
}
