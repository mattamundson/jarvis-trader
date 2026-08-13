"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchStrategyGates, type GateResult, type GatesResponse } from "@/lib/api";

function fmtVal(g: GateResult): string {
  if (g.value === null || !Number.isFinite(g.value)) return "—";
  const digits = g.key === "sample" ? 0 : 2;
  return `${g.value.toFixed(digits)}${g.unit ?? ""}`;
}

function fmtThreshold(g: GateResult): string {
  if (g.threshold === null) return "shadow";
  const digits = g.key === "sample" ? 0 : 2;
  return `${g.comparator} ${g.threshold.toFixed(digits)}${g.unit ?? ""}`;
}

/** Pass = green, Fail = red, not-evaluable/shadow = muted. */
function gateStyle(passed: boolean | null): { bg: string; border: string; label: string } {
  if (passed === true) return { bg: "rgba(21,128,61,0.12)", border: "#15803d", label: "PASS" };
  if (passed === false) return { bg: "rgba(185,28,28,0.12)", border: "#b91c1c", label: "FAIL" };
  return { bg: "rgba(120,120,120,0.10)", border: "#6b7280", label: "—" };
}

/**
 * Live production-gate scorecard for one symbol: renders the 6 gate-v2 gates
 * (PF-CI, p_edge, MC DD, DSR, OOS sample, win-rate CI) with pass/fail styling +
 * value vs threshold, read from GET /strategy/gates/{symbol}. Edge readiness (C1)
 * becomes visible per-gate, not just a single PASS/FAIL.
 */
export function ProdGateScorecard({ symbol }: { symbol: string }) {
  const { data, error, isLoading } = useSWR<GatesResponse>(
    symbol ? `strategy-gates-${symbol}` : null,
    () => fetchStrategyGates(symbol),
    { refreshInterval: POLL_INTERVAL.MINUTE }
  );

  if (!symbol) return null;

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">
          Production gates · {symbol}
        </h2>
        {data && (
          <span className="font-mono text-xs text-muted-foreground">
            {data.n_pass}/{data.n_total} pass
            {data.n_evaluated < data.n_total ? ` · ${data.n_total - data.n_evaluated} shadow` : ""}
            {data.verdict ? ` · verdict ${data.verdict}` : ""}
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-muted-foreground">Loading gates…</p>}
      {error && <p className="text-xs text-destructive">Error loading gates</p>}

      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {data.gates.map((g) => {
            const s = gateStyle(g.passed);
            return (
              <div
                key={g.key}
                className="rounded-md px-3 py-2 flex flex-col gap-0.5"
                style={{ backgroundColor: s.bg, border: `1px solid ${s.border}` }}
                title={g.note ?? undefined}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-muted-foreground truncate">
                    {g.label}
                  </span>
                  <span
                    className="font-mono text-[10px] font-bold shrink-0"
                    style={{ color: s.border }}
                  >
                    {s.label}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-sm font-semibold text-foreground">
                    {fmtVal(g)}
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground shrink-0">
                    {fmtThreshold(g)}
                  </span>
                </div>
                {!g.enforced && (
                  <span className="font-mono text-[9px] uppercase tracking-wide text-muted-foreground/70">
                    shadow
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
