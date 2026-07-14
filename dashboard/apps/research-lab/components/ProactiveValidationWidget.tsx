"use client";

import useSWR from "swr";
import { CheckCircle, XCircle, AlertTriangle, Clock, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

type CheckStatus = "pass" | "warn" | "fail" | "insufficient";

interface ValidationCheck {
  name: string;
  status: CheckStatus;
  value: string;
  threshold: string;
  detail?: string;
}

interface ProactiveSuiteResponse {
  symbol: string;
  overall: "READY" | "CAUTION" | "NOT_READY" | "INSUFFICIENT_DATA";
  checks: {
    validation_gates?: { status: CheckStatus; pf?: number; sharpe?: number; wr?: number; max_dd?: number };
    trade_count?: { status: CheckStatus; count?: number; minimum?: number };
    time_elapsed?: { status: CheckStatus; days?: number; minimum?: number };
    wfe_status?: { status: CheckStatus; wfe?: number };
    mc_edge?: { status: CheckStatus; p_value?: number };
    consecutive_loss?: { status: CheckStatus; streak?: number };
    wr_trajectory?: { status: CheckStatus; recent_wr?: number; lifetime_wr?: number };
    slippage?: { status: CheckStatus; avg_ticks?: number };
  };
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function fetcher<T = unknown>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function overallBadgeVariant(
  overall: ProactiveSuiteResponse["overall"]
): "bull" | "warn" | "bear" | "neutral" {
  if (overall === "READY") return "bull";
  if (overall === "CAUTION") return "warn";
  if (overall === "NOT_READY") return "bear";
  return "neutral";
}

function statusIcon(status: CheckStatus) {
  if (status === "pass") return <CheckCircle className="h-3.5 w-3.5 text-bull" />;
  if (status === "warn") return <AlertTriangle className="h-3.5 w-3.5 text-warn" />;
  if (status === "fail") return <XCircle className="h-3.5 w-3.5 text-bear" />;
  return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
}

function statusBorder(status: CheckStatus): string {
  if (status === "pass") return "border-bull/20 bg-bull/5";
  if (status === "warn") return "border-warn/20 bg-warn/5";
  if (status === "fail") return "border-bear/20 bg-bear/5";
  return "border-border bg-card";
}

function parseChecks(data: ProactiveSuiteResponse): ValidationCheck[] {
  const c = data.checks ?? {};
  return [
    {
      name: "Validation Gates",
      status: c.validation_gates?.status ?? "insufficient",
      value: c.validation_gates
        ? `PF ${(c.validation_gates.pf ?? 0).toFixed(2)} / SR ${(c.validation_gates.sharpe ?? 0).toFixed(2)}`
        : "—",
      threshold: "PF ≥ 2.0 / SR ≥ 1.5",
    },
    {
      name: "Trade Count",
      status: c.trade_count?.status ?? "insufficient",
      value: c.trade_count ? `${c.trade_count.count ?? 0}` : "—",
      threshold: "≥ 60 trades",
    },
    {
      name: "Time Elapsed",
      status: c.time_elapsed?.status ?? "insufficient",
      value: c.time_elapsed ? `${c.time_elapsed.days ?? 0}d` : "—",
      threshold: "≥ 30 days",
    },
    {
      name: "WFE Status",
      status: c.wfe_status?.status ?? "insufficient",
      value: c.wfe_status ? (c.wfe_status.wfe ?? 0).toFixed(2) : "—",
      threshold: "≥ 0.50 (warn < 0.30)",
    },
    {
      name: "MC Edge Sig.",
      status: c.mc_edge?.status ?? "insufficient",
      value: c.mc_edge ? `p=${(c.mc_edge.p_value ?? 1).toFixed(3)}` : "—",
      threshold: "p < 0.05",
    },
    {
      name: "Consec. Losses",
      status: c.consecutive_loss?.status ?? "insufficient",
      value: c.consecutive_loss ? `${c.consecutive_loss.streak ?? 0}` : "—",
      threshold: "warn ≥ 3 / fail ≥ 5",
    },
    {
      name: "WR Trajectory",
      status: c.wr_trajectory?.status ?? "insufficient",
      value: c.wr_trajectory
        ? `L20: ${((c.wr_trajectory.recent_wr ?? 0) * 100).toFixed(1)}% / Life: ${((c.wr_trajectory.lifetime_wr ?? 0) * 100).toFixed(1)}%`
        : "—",
      threshold: "recent vs lifetime (−10pp)",
    },
    {
      name: "Slippage",
      status: c.slippage?.status ?? "insufficient",
      value: c.slippage ? `${(c.slippage.avg_ticks ?? 0).toFixed(2)} tks` : "—",
      threshold: "≤ 1.5 ticks",
    },
  ];
}

// ── Symbol Panel ──────────────────────────────────────────────────────────

function SymbolPanel({ symbol }: { symbol: string }) {
  const { data, error } = useSWR<ProactiveSuiteResponse>(
    `/validate/proactive-suite?symbol=${symbol}`,
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  const loading = !data && !error;

  if (loading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-xs font-bold text-foreground">{symbol}</span>
          <div className="h-5 w-20 animate-pulse rounded bg-muted" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg border border-border bg-muted/30" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-xs font-bold text-foreground">{symbol}</span>
          <Badge variant="neutral">UNAVAILABLE</Badge>
        </div>
        <p className="text-xs text-muted-foreground font-mono">Engine offline or validation data unavailable.</p>
      </div>
    );
  }

  const overall = data.overall ?? "INSUFFICIENT_DATA";
  const checks = parseChecks(data);
  const badgeVariant = overallBadgeVariant(overall);

  return (
    <div className="space-y-2">
      {/* Symbol header */}
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-xs font-bold" style={{ color: "#e0e0e0" }}>{symbol}</span>
        <Badge variant={badgeVariant}>{overall.replace("_", " ")}</Badge>
      </div>

      {/* 2×4 check grid */}
      <div className="grid grid-cols-2 gap-2">
        {checks.map((chk) => (
          <div
            key={chk.name}
            className={`rounded-lg border p-2 space-y-1 ${statusBorder(chk.status)}`}
          >
            <div className="flex items-center gap-1.5">
              {statusIcon(chk.status)}
              <span className="font-mono text-[10px] text-muted-foreground truncate">{chk.name}</span>
            </div>
            <p className="font-mono text-xs font-bold tabular-nums" style={{ color: "#e0e0e0" }}>
              {chk.value}
            </p>
            <p className="font-mono text-[9px] text-muted-foreground/70 leading-none">{chk.threshold}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────

export function ProactiveValidationWidget() {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <ShieldCheck className="h-4 w-4 text-cyan-400" />
        <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-cyan-400">
          Proactive Validation Suite
        </span>
        <span className="ml-auto font-mono text-[9px] text-zinc-600 uppercase tracking-wider">
          8 checks · 60s poll
        </span>
      </div>

      {/* Divider */}
      <div className="h-px bg-zinc-800 mb-4" />

      {/* Two symbols side by side */}
      <div className="grid grid-cols-2 gap-6">
        <SymbolPanel symbol="MCL" />
        <div className="w-px bg-zinc-800" />
        <div style={{ marginTop: "-1rem" }}>
          <SymbolPanel symbol="MNQ" />
        </div>
      </div>
    </div>
  );
}
