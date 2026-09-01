"use client";

import {
  BookOpen,
  CheckCircle,
  ChevronRight,
  Database,
  TrendingUp,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type CommandCenterDataIntegrityResponse,
  type CommandCenterDecision,
  type CommandCenterPaperStatusRow,
  type CommandCenterPortfolioData,
  type CommandCenterTrade,
  type LedgerResponse,
} from "@/lib/commandCenterApi";
import { dedupCaveat, type HonestTradeSet } from "@/lib/honestTrades";

type ShellTone = "live" | "warn" | "offline" | "static";
type StatusTone = "ok" | "warn" | "bad" | "unknown";

export interface ShellRegion {
  label: string;
  href: string;
  status: string;
  metric: string;
  detail: string;
  tone: ShellTone;
  Icon: LucideIcon;
}

type StatusStripCell = {
  label: string;
  detail: string;
  tone: StatusTone;
};

type LiveInstrument = {
  symbol: string;
  tf: string;
  status: "APPROVED" | "HALTED";
  wfe: number;
};

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

function shellToneClass(tone: ShellTone): string {
  if (tone === "live") return "border-emerald-800/50 bg-emerald-950/10 text-emerald-300";
  if (tone === "warn") return "border-amber-800/50 bg-amber-950/10 text-amber-300";
  if (tone === "offline") return "border-red-800/50 bg-red-950/10 text-red-300";
  return "border-slate-800 bg-slate-900/60 text-slate-300";
}

export function compactCount(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function statusToneClass(tone: StatusTone): string {
  if (tone === "ok") return "border-emerald-800 bg-emerald-950/25 text-emerald-300";
  if (tone === "warn") return "border-amber-800 bg-amber-950/25 text-amber-300";
  if (tone === "bad") return "border-red-800 bg-red-950/25 text-red-300";
  return "border-slate-800 bg-slate-900/70 text-slate-400";
}

export function CommandCenterStatusStrip({
  engine,
  broker,
  safety,
  data,
}: {
  engine: StatusStripCell;
  broker: StatusStripCell;
  safety: StatusStripCell;
  data: StatusStripCell;
}) {
  const rows = [
    { title: "ENGINE", ...engine },
    { title: "BROKER", ...broker },
    { title: "SAFETY", ...safety },
    { title: "DATA", ...data },
  ];
  return (
    <section
      data-testid="command-center-status-strip"
      className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-slate-800 bg-slate-950/60 p-2 md:grid-cols-2 xl:grid-cols-4"
      aria-label="Command Center independent status strip"
    >
      {rows.map((row) => (
        <div
          key={row.title}
          className={`rounded-md border px-3 py-2 ${statusToneClass(row.tone)}`}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-[10px] font-mono font-bold tracking-widest text-slate-500">
              {row.title}
            </span>
            <span className="text-[10px] font-mono uppercase tracking-wider">
              {row.label}
            </span>
          </div>
          <p className="mt-1 truncate text-[11px] font-mono text-slate-500" title={row.detail}>
            {row.detail}
          </p>
        </div>
      ))}
    </section>
  );
}

export function CommandCenterTradeQueuePanel({
  decisions,
  decisionsErr,
  portfolio,
  portfolioErr,
  trades,
  tradesErr,
  honestSet,
}: {
  decisions: CommandCenterDecision[] | undefined;
  decisionsErr: unknown;
  portfolio: CommandCenterPortfolioData | undefined;
  portfolioErr: unknown;
  trades: CommandCenterTrade[] | undefined;
  tradesErr: unknown;
  honestSet: HonestTradeSet | undefined;
}) {
  const decisionRows = Array.isArray(decisions) ? decisions : [];
  const positions = Array.isArray(portfolio?.positions) ? portfolio.positions : [];
  const fillRows = Array.isArray(trades) ? trades : [];
  const isDegraded = Boolean(decisionsErr || portfolioErr || tradesErr);
  const isEmpty = !isDegraded && decisionRows.length === 0 && positions.length === 0 && fillRows.length === 0;
  const stopState = portfolioErr
    ? "unknown"
    : positions.length > 0
      ? "contract needed"
      : "clear";
  const stopTone: StatusTone = portfolioErr ? "unknown" : positions.length > 0 ? "warn" : "ok";
  const journalLabel = honestSet ? dedupCaveat(honestSet) : "honest journal unavailable";

  const cells = [
    {
      title: "DECISIONS",
      label: decisionsErr ? "unknown" : `${decisionRows.length} recent`,
      detail: decisionsErr ? "decision endpoint unavailable" : "latest directional verdict rows",
      tone: decisionsErr ? "unknown" as const : "ok" as const,
    },
    {
      title: "POSITIONS",
      label: portfolioErr ? "unknown" : `${positions.length} open`,
      detail: portfolioErr ? "portfolio endpoint unavailable" : "paper portfolio source",
      tone: portfolioErr ? "unknown" as const : positions.length > 0 ? "warn" as const : "ok" as const,
    },
    {
      title: "STOP REVIEW",
      label: stopState,
      detail: positions.length > 0
        ? "stale-stop backend contract not mounted here"
        : "no open position stop check required",
      tone: stopTone,
    },
    {
      title: "JOURNAL",
      label: honestSet ? `${honestSet.trades.length} real` : "unknown",
      detail: journalLabel,
      tone: honestSet ? "ok" as const : "unknown" as const,
    },
  ];

  return (
    <section
      data-testid="command-center-trade-queue-panel"
      className="mb-4 rounded-md border border-slate-800 bg-slate-900/55 p-4"
      aria-label="Command Center trade queue panel"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-cyan-400" aria-hidden="true" />
          <h2 className="text-sm font-bold tracking-widest text-white">TRADE QUEUE PANEL</h2>
        </div>
        <Badge className="border border-slate-700 bg-slate-950 text-[10px] font-mono text-slate-400">
          ORDER ACTIONS DISABLED
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
        {cells.map((cell) => (
          <div key={cell.title} className={`rounded-md border px-3 py-2 ${statusToneClass(cell.tone)}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-mono font-bold tracking-widest text-slate-500">
                {cell.title}
              </span>
              <span className="text-[10px] font-mono uppercase tracking-wider">
                {cell.label}
              </span>
            </div>
            <p className="mt-1 truncate text-[11px] font-mono text-slate-500" title={cell.detail}>
              {cell.detail}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/45 p-3">
        {isDegraded ? (
          <p className="text-xs font-mono text-amber-300">
            Queue degraded: one or more queue sources are unavailable.
          </p>
        ) : isEmpty ? (
          <p className="text-xs font-mono text-slate-400">
            No directional queue items, open paper positions, or recent fills are present.
          </p>
        ) : (
          <div className="space-y-2">
            {decisionRows.slice(0, 3).map((decision, index) => (
              <div
                key={`${decision.timestamp}-${decision.symbol}-${index}`}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-800/60 pb-2 last:border-b-0 last:pb-0"
              >
                <span className="font-mono text-xs font-bold text-white">{decision.symbol}</span>
                <span className="font-mono text-xs text-cyan-300">{decision.action}</span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-slate-500">
                  {decision.reason ?? decision.signal ?? "reason unavailable"}
                </span>
                <span className="font-mono text-[10px] text-slate-600">{fmtTime(decision.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function stateBadgeClass(tone: StatusTone): string {
  if (tone === "ok") return "border-emerald-800 bg-emerald-950/30 text-emerald-300";
  if (tone === "warn") return "border-amber-800 bg-amber-950/30 text-amber-300";
  if (tone === "bad") return "border-red-800 bg-red-950/30 text-red-300";
  return "border-slate-700 bg-slate-950 text-slate-400";
}

function MiniStateBadge({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider ${stateBadgeClass(tone)}`}>
      {label}
    </span>
  );
}

export function CommandCenterOperationsGrid({
  liveInstruments,
  paperStatus,
  ledger,
  ledgerReady,
  integrity,
  integrityReady,
}: {
  liveInstruments: LiveInstrument[];
  paperStatus: Record<string, CommandCenterPaperStatusRow> | undefined;
  ledger: LedgerResponse | undefined;
  ledgerReady: boolean;
  integrity: CommandCenterDataIntegrityResponse | undefined;
  integrityReady: boolean;
}) {
  const eligibilityRows = liveInstruments.map((inst) => {
    const row = paperStatus?.[`${inst.symbol}_${inst.tf}`];
    const raw = (row?.status ?? "").toUpperCase();
    const label = !paperStatus
      ? "stale"
      : raw === "ACTIVE" && inst.status === "APPROVED"
        ? "adopted"
        : raw === "NO-TRADE"
          ? "paused"
          : raw === "FAIL" || inst.status === "HALTED"
            ? "failed"
            : "research-only";
    const tone: StatusTone =
      label === "adopted" ? "ok" : label === "failed" ? "bad" : label === "paused" ? "warn" : "unknown";
    return {
      ...inst,
      label,
      tone,
      detail: row?.reason ?? row?.verdict ?? `DSR ${inst.wfe}`,
    };
  });

  const ledgerRows = Array.isArray(ledger?.entries) ? ledger.entries.slice(0, 4) : [];
  const integritySources = Array.isArray(integrity?.sources) ? integrity.sources : [];
  const staleSourceCount = integritySources.filter((src) => src.status === "stale").length;
  const dataRows = [
    {
      label: "CACHE AGE",
      state: integrityReady ? "reported" : "unknown",
      tone: integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "PROVIDER",
      state: integrityReady ? `${integrity?.count ?? integritySources.length} streams` : "unknown",
      tone: integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "BAR FRESHNESS",
      state: staleSourceCount > 0 ? `${staleSourceCount} stale` : integrityReady ? "current" : "unknown",
      tone: staleSourceCount > 0 ? "warn" as const : integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "SOURCE PARITY",
      state: "not wired",
      tone: "unknown" as const,
    },
  ];
  const researchRows = [
    { label: "PRS", state: "intake", detail: "keep / split / replace" },
    { label: "ISSUES", state: "intake", detail: "acceptance before code" },
    { label: "EXPERIMENTS", state: "research-only", detail: "no readiness promotion" },
    { label: "SPIKES", state: "reference", detail: "retire-to-archive when superseded" },
  ];

  return (
    <section
      data-testid="command-center-operations-grid"
      className="mb-4 grid grid-cols-1 gap-3 xl:grid-cols-4"
      aria-label="Command Center operations panels"
    >
      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <CheckCircle className="w-3 h-3" />
            ELIGIBILITY PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2.5">
          <div className="flex flex-wrap gap-1">
            <MiniStateBadge label="adopted" tone="ok" />
            <MiniStateBadge label="paused" tone="warn" />
            <MiniStateBadge label="failed" tone="bad" />
            <MiniStateBadge label="stale" tone="unknown" />
            <MiniStateBadge label="research-only" tone="unknown" />
          </div>
          {eligibilityRows.map((row) => (
            <div key={`${row.symbol}-${row.tf}`} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-white">{row.symbol} {row.tf}</span>
              <MiniStateBadge label={row.label} tone={row.tone} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <TrendingUp className="w-3 h-3" />
            STRATEGY LEDGER PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {!ledgerReady ? (
            <p className="text-xs font-mono text-amber-300">Ledger unavailable.</p>
          ) : ledgerRows.length === 0 ? (
            <p className="text-xs font-mono text-slate-400">No strategy verdicts reported.</p>
          ) : (
            ledgerRows.map((row, index) => {
              const verdict = row.verdict ?? "UNKNOWN";
              const tone: StatusTone = verdict === "PASS" ? "ok" : verdict === "FAIL" ? "bad" : "unknown";
              const nextGate = verdict === "PASS" ? "forward proof" : verdict === "FAIL" ? "repair thesis" : "gate-v2 rerun";
              return (
                <div key={`${row.symbol}-${row.family}-${index}`} className="rounded border border-slate-800 bg-slate-950/40 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-white">{row.symbol ?? "—"} {row.family ?? "unknown"}</span>
                    <MiniStateBadge label={verdict} tone={tone} />
                  </div>
                  <p className="mt-1 text-[11px] font-mono text-slate-500">
                    next gate: {nextGate}
                  </p>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <Database className="w-3 h-3" />
            DATA INTEGRITY PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {dataRows.map((row) => (
            <div key={row.label} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-slate-500">{row.label}</span>
              <MiniStateBadge label={row.state} tone={row.tone} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <BookOpen className="w-3 h-3" />
            RESEARCH INTAKE PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {researchRows.map((row) => (
            <div key={row.label} className="rounded border border-slate-800 bg-slate-950/40 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-white">{row.label}</span>
                <MiniStateBadge label={row.state} tone="unknown" />
              </div>
              <p className="mt-1 text-[11px] font-mono text-slate-500">{row.detail}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}

export function CanonicalShellMap({ regions }: { regions: ShellRegion[] }) {
  return (
    <section
      className="mb-4"
      aria-label="Command Center canonical sections"
      data-testid="canonical-shell"
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-mono tracking-[0.2em] text-slate-500">
          CANONICAL SHELL
        </span>
        <span className="text-[10px] font-mono text-slate-600">
          {regions.filter((r) => r.tone === "live").length}/{regions.length} live
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-6">
        {regions.map((region) => {
          const Icon = region.Icon;
          return (
            <a
              key={region.label}
              data-testid={`canonical-shell-${region.label.toLowerCase().replace(/\s+/g, "-")}`}
              href={region.href}
              className={`group min-h-[112px] rounded-md border p-3 transition-colors hover:border-cyan-700/70 ${shellToneClass(region.tone)}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate text-[11px] font-bold tracking-widest">
                    {region.label}
                  </span>
                </div>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-40 transition-opacity group-hover:opacity-80" aria-hidden="true" />
              </div>
              <div className="mt-3 font-mono text-lg font-bold leading-none text-white tabular-nums">
                {region.metric}
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-[10px] font-mono uppercase tracking-wider opacity-80">
                  {region.status}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-slate-500">
                {region.detail}
              </p>
            </a>
          );
        })}
      </div>
    </section>
  );
}
