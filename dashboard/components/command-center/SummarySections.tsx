"use client";

import {
  deriveCommandCenterDailyBriefSummaryRows,
  deriveCommandCenterOperationsSummaryRows,
  deriveCommandCenterTrustAuditSummaryRows,
  type CommandCenterStatusTone,
} from "@/lib/commandCenterState";
import type {
  CommandCenterBarQualityData,
  CommandCenterEdgeLedgerData,
  CommandCenterHealthData,
  CommandCenterMacroData,
  CommandCenterSafetyData,
  CommandCenterSessionTodayData,
} from "@/lib/commandCenterApi";
import type { ExecutionStatus } from "@/lib/executionPath";

function stateBadgeClass(tone: CommandCenterStatusTone): string {
  if (tone === "ok") return "border-emerald-800 bg-emerald-950/30 text-emerald-300";
  if (tone === "warn") return "border-amber-800 bg-amber-950/30 text-amber-300";
  if (tone === "bad") return "border-red-800 bg-red-950/30 text-red-300";
  return "border-slate-700 bg-slate-950 text-slate-400";
}

function MiniStateBadge({ label, tone }: { label: string; tone: CommandCenterStatusTone }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider ${stateBadgeClass(tone)}`}>
      {label}
    </span>
  );
}

export function CommandCenterOperationsSummary({
  health,
  healthErr,
  safety,
  safetyErr,
  execution,
}: {
  health: CommandCenterHealthData | undefined;
  healthErr: boolean;
  safety: CommandCenterSafetyData | undefined;
  safetyErr: boolean;
  execution: ExecutionStatus;
}) {
  const rows = deriveCommandCenterOperationsSummaryRows({
    health,
    healthErr,
    safety,
    safetyErr,
    execution,
  });

  return (
    <section
      className="mb-4 rounded-md border border-slate-800 bg-slate-950/35 p-3"
      aria-label="Command Center operations summary"
      data-testid="command-center-operations-summary"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-mono tracking-[0.2em] text-slate-500">
          OPERATIONS SUMMARY
        </span>
        <a href="/command-center?view=operations" className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 hover:text-cyan-300">
          operations view
        </a>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
        {rows.map((row) => (
          <div key={row.label} className="rounded border border-slate-800 bg-slate-950/40 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
                {row.label}
              </span>
              <MiniStateBadge label={row.state} tone={row.tone} />
            </div>
            <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-slate-500">
              {row.detail}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CommandCenterDailyBriefSummary({
  health,
  sessionToday,
  sessionTodayErr,
  macro,
}: {
  health: CommandCenterHealthData | undefined;
  sessionToday: CommandCenterSessionTodayData | undefined;
  sessionTodayErr: boolean;
  macro: CommandCenterMacroData | undefined;
}) {
  const rows = deriveCommandCenterDailyBriefSummaryRows({
    health,
    sessionToday,
    sessionTodayErr,
    macro,
  });

  return (
    <section
      className="mb-4 rounded-md border border-slate-800 bg-slate-950/35 p-3"
      aria-label="Command Center daily brief summary"
      data-testid="command-center-daily-brief-summary"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-mono tracking-[0.2em] text-slate-500">
          DAILY BRIEF SUMMARY
        </span>
        <a href="/today" className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 hover:text-cyan-300">
          today drilldown
        </a>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
        {rows.map((row) => (
          <div key={row.label} className="rounded border border-slate-800 bg-slate-950/40 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
                {row.label}
              </span>
              <MiniStateBadge label={row.state} tone={row.tone} />
            </div>
            <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-slate-500">
              {row.detail}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CommandCenterTrustAuditSummary({
  health,
  healthErr,
  barQuality,
  barQualityErr,
  edgeLedger,
  edgeLedgerErr,
}: {
  health: CommandCenterHealthData | undefined;
  healthErr: boolean;
  barQuality: CommandCenterBarQualityData | undefined;
  barQualityErr: boolean;
  edgeLedger: CommandCenterEdgeLedgerData | undefined;
  edgeLedgerErr: boolean;
}) {
  const rows = deriveCommandCenterTrustAuditSummaryRows({
    health,
    healthErr,
    barQuality,
    barQualityErr,
    edgeLedger,
    edgeLedgerErr,
  });

  return (
    <section
      className="mb-4 rounded-md border border-slate-800 bg-slate-950/35 p-3"
      aria-label="Command Center trust audit summary"
      data-testid="command-center-trust-audit-summary"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-mono tracking-[0.2em] text-slate-500">
          TRUST AUDIT SUMMARY
        </span>
        <a href="/trust-pane" className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 hover:text-cyan-300">
          trust pane
        </a>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {rows.map((row) => (
          <div key={row.label} className="rounded border border-slate-800 bg-slate-950/40 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
                {row.label}
              </span>
              <MiniStateBadge label={row.state} tone={row.tone} />
            </div>
            <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-slate-500">
              {row.detail}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
