"use client";

import useSWR from "swr";
import {
  fetchEquityResearch,
  type EquityCertRow,
  type ForwardCandidateRow,
  type EquityResearchResponse,
} from "@/lib/api";

// Thresholds for equity-class certification (not the futures 6% bar)
const EQUITY_DD_CEILING = 25.0;
const T_PF = 1.1;
const T_PEDGE = 0.95;
const T_DSR = 0.1;

function fmt(v: number | null, digits = 2): string {
  return v === null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

function equityTileStyle(passed: boolean | null): { bg: string; border: string } {
  if (passed === true) return { bg: "rgba(21,128,61,0.12)", border: "#15803d" };
  if (passed === false) return { bg: "rgba(185,28,28,0.12)", border: "#b91c1c" };
  return { bg: "rgba(120,120,120,0.10)", border: "#6b7280" };
}

function EquityCertTile({ c }: { c: EquityCertRow }) {
  const ddPassEquity = c.mc_95th_dd_pct === null ? null : c.mc_95th_dd_pct <= EQUITY_DD_CEILING;
  return (
    <div className="border border-border rounded-lg p-3 bg-card/60 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="font-mono text-sm font-bold text-foreground">
            {c.symbol} SMA({c.fast},{c.slow})×{c.atr_mult}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {c.n_windows} windows · {c.total_oos_trades} OOS trades
          </span>
        </div>
        <span
          className="font-mono text-[10px] font-bold shrink-0 rounded px-1.5 py-0.5"
          style={{
            backgroundColor: c.verdict === "PASS" ? "rgba(21,128,61,0.15)" : "rgba(185,28,28,0.15)",
            border: `1px solid ${c.verdict === "PASS" ? "#15803d" : "#b91c1c"}`,
            color: c.verdict === "PASS" ? "#4ade80" : "#f87171",
          }}
        >
          {c.verdict}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-1.5">
        <div
          className="rounded-md px-2 py-1.5 flex flex-col gap-0.5"
          style={{
            backgroundColor: equityTileStyle(c.pf_ci_lower === null ? null : c.pf_ci_lower >= T_PF).bg,
            border: `1px solid ${equityTileStyle(c.pf_ci_lower === null ? null : c.pf_ci_lower >= T_PF).border}`,
          }}
        >
          <span className="font-mono text-[10px] text-muted-foreground">PF-CI lo</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.pf_ci_lower)}</span>
        </div>
        <div
          className="rounded-md px-2 py-1.5 flex flex-col gap-0.5"
          style={{
            backgroundColor: equityTileStyle(c.p_edge === null ? null : c.p_edge >= T_PEDGE).bg,
            border: `1px solid ${equityTileStyle(c.p_edge === null ? null : c.p_edge >= T_PEDGE).border}`,
          }}
        >
          <span className="font-mono text-[10px] text-muted-foreground">P(edge)</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.p_edge)}</span>
        </div>
        <div
          className="rounded-md px-2 py-1.5 flex flex-col gap-0.5"
          style={{
            backgroundColor: equityTileStyle(c.dsr === null ? null : c.dsr >= T_DSR).bg,
            border: `1px solid ${equityTileStyle(c.dsr === null ? null : c.dsr >= T_DSR).border}`,
          }}
        >
          <span className="font-mono text-[10px] text-muted-foreground">DSR</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.dsr)}</span>
        </div>
        <div
          className="rounded-md px-2 py-1.5 flex flex-col gap-0.5"
          style={{
            backgroundColor: equityTileStyle(ddPassEquity).bg,
            border: `1px solid ${equityTileStyle(ddPassEquity).border}`,
          }}
        >
          <span className="font-mono text-[10px] text-muted-foreground">MC-DD %</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.mc_95th_dd_pct)}</span>
        </div>
      </div>

      {c.note && (
        <p className="font-mono text-[11px] text-muted-foreground leading-snug">{c.note}</p>
      )}
    </div>
  );
}

function ForwardEvidenceTile({ c }: { c: ForwardCandidateRow }) {
  return (
    <div className="border border-border rounded-lg p-3 bg-card/60 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="font-mono text-sm font-bold text-foreground">
            {c.id}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {c.symbol} · {c.forward_n_windows} fwd windows · {c.forward_total_trades} trades
          </span>
        </div>
        <span
          className="font-mono text-[10px] font-bold shrink-0 rounded px-1.5 py-0.5"
          style={{
            backgroundColor: c.graduated ? "rgba(21,128,61,0.15)" : "rgba(120,120,120,0.10)",
            border: `1px solid ${c.graduated ? "#15803d" : "#6b7280"}`,
            color: c.graduated ? "#4ade80" : "#9ca3af",
          }}
        >
          {c.graduated ? "GRADUATED" : "ACTIVE"}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-1.5">
        <div className="rounded-md px-2 py-1.5 flex flex-col gap-0.5 bg-muted">
          <span className="font-mono text-[10px] text-muted-foreground">P(edge)</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.forward_p_edge)}</span>
        </div>
        <div className="rounded-md px-2 py-1.5 flex flex-col gap-0.5 bg-muted">
          <span className="font-mono text-[10px] text-muted-foreground">PF-CI lo</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.forward_pf_ci_lower)}</span>
        </div>
        <div className="rounded-md px-2 py-1.5 flex flex-col gap-0.5 bg-muted">
          <span className="font-mono text-[10px] text-muted-foreground">PnL</span>
          <span className="font-mono text-sm font-semibold text-foreground">{fmt(c.forward_total_pnl, 0)}</span>
        </div>
        <div className="rounded-md px-2 py-1.5 flex flex-col gap-0.5 bg-muted">
          <span className="font-mono text-[10px] text-muted-foreground">Shuffle</span>
          <span className="font-mono text-sm font-semibold text-foreground">{c.shuffle_passes ? "✓" : "✗"}</span>
        </div>
      </div>

      {c.reason && (
        <p className="font-mono text-[11px] text-muted-foreground leading-snug">{c.reason}</p>
      )}
    </div>
  );
}

export function EquityResearchPanel() {
  const { data, error, isLoading } = useSWR<EquityResearchResponse>(
    "equity-research",
    fetchEquityResearch,
    { refreshInterval: 300000 }
  );

  const certs = data?.equity_certs ?? [];
  const fwd = data?.forward_evidence ?? [];
  const nPass = certs.filter(c => c.verdict === "PASS").length;
  const nGraduated = fwd.filter(c => c.graduated).length;

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">Equity Research · Daily SMA-Trend</h2>
        {data && (
          <span className="font-mono text-xs text-muted-foreground">
            {certs.length} certs · {nPass} PASS · {fwd.length} fwd · {nGraduated} graduated
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-muted-foreground">Loading equity research data…</p>}
      {error && <p className="text-xs text-destructive">Error loading equity research</p>}
      {data && certs.length === 0 && fwd.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No equity research data yet. Run equity SMA-trend certification to populate.
        </p>
      )}

      {certs.length > 0 && (
        <div className="mb-6">
          <h3 className="font-mono text-xs font-semibold text-muted-foreground mb-2">
            Daily SMA-Trend Certification (WFO, 113 windows)
          </h3>
          <div className="flex flex-col gap-2">
            {certs.map((c) => (
              <EquityCertTile key={c.source_file} c={c} />
            ))}
          </div>
        </div>
      )}

      {fwd.length > 0 && (
        <div>
          <h3 className="font-mono text-xs font-semibold text-muted-foreground mb-2">
            Forward Evidence (Closed-Trade Ledger)
          </h3>
          <div className="flex flex-col gap-2">
            {fwd.map((c) => (
              <ForwardEvidenceTile key={c.id} c={c} />
            ))}
          </div>
        </div>
      )}

      <p className="font-mono text-[10px] text-muted-foreground/70 mt-3">
        Non-authorizing research namespace — never routes capital. DD judged vs equity-class ceiling.
      </p>
    </div>
  );
}