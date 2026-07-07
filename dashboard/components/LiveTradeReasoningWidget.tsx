"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type {
  RecentPipelineReasoningResponse,
  RecentPipelineDecision,
  DebateResult,
  AgentAnalystReport,
  PipelineDecisionSnapshot,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function actionColor(action: unknown): string {
  // Coerce defensively — the engine sometimes sends non-string enum-ish values.
  const a = String(action ?? "").toLowerCase();
  if (a === "buy" || a === "long") return "text-emerald-400";
  if (a === "sell" || a === "short") return "text-red-400";
  return "text-slate-400";
}

// Analyst `signal` is a numeric score (~ -1..1), NOT a string action enum.
// Treating it as a string (.toLowerCase/.toUpperCase) crashes the whole page.
function signalColor(signal: unknown): string {
  const n = typeof signal === "number" ? signal : Number(signal);
  if (Number.isFinite(n)) {
    if (n > 0.05) return "text-emerald-400";
    if (n < -0.05) return "text-red-400";
    return "text-slate-400";
  }
  return actionColor(signal); // legacy string signals ("buy"/"sell")
}

function formatSignal(signal: unknown): string {
  const n = typeof signal === "number" ? signal : Number(signal);
  if (Number.isFinite(n)) return n > 0 ? `+${n.toFixed(2)}` : n.toFixed(2);
  return String(signal ?? "").toUpperCase();
}

function verdictColor(verdict?: string): string {
  if (!verdict) return "text-slate-400";
  const v = verdict.toUpperCase();
  if (v.includes("BULL")) return "text-emerald-400";
  if (v.includes("BEAR")) return "text-red-400";
  if (v.includes("INCONCLU")) return "text-amber-400";
  return "text-slate-400";
}

function regimeColor(regime?: string): string {
  if (!regime) return "text-slate-500";
  const r = regime.toUpperCase();
  if (r.includes("BULL")) return "text-emerald-400";
  if (r.includes("BEAR")) return "text-red-400";
  if (r.includes("RANGING") || r.includes("MIXED")) return "text-amber-400";
  return "text-slate-400";
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface StageRowProps {
  label: string;
  children: React.ReactNode;
  approved?: boolean | null;
}

function StageRow({ label, children, approved }: StageRowProps) {
  const border =
    approved === true
      ? "border-l-2 border-emerald-700"
      : approved === false
      ? "border-l-2 border-red-700"
      : "border-l-2 border-slate-700";
  return (
    <div className={`pl-2 py-0.5 ${border} flex items-start gap-2 text-xs`}>
      <span className="text-slate-500 font-mono w-20 shrink-0">{label}</span>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">{children}</div>
    </div>
  );
}

function AnalystRow({
  name,
  report,
  expanded,
}: {
  name: string;
  report?: AgentAnalystReport | null;
  expanded?: boolean;
}) {
  if (!report) {
    return (
      <StageRow label={`S1 ${name.toUpperCase()}`}>
        <span className="text-slate-600">no data</span>
      </StageRow>
    );
  }
  return (
    <StageRow label={`S1 ${name.toUpperCase()}`}>
      {report.regime && (
        <span className={`font-mono ${regimeColor(report.regime)}`}>{report.regime}</span>
      )}
      {report.stc_val != null && (
        <span className="text-slate-300 font-mono">STC {report.stc_val.toFixed(1)}</span>
      )}
      {report.signal != null && (
        <span className={signalColor(report.signal)}>{formatSignal(report.signal)}</span>
      )}
      {report.sentiment && (
        <span className="text-slate-400">{report.sentiment}</span>
      )}
      {report.bias && (
        <span className={regimeColor(report.bias)}>{report.bias}</span>
      )}
      {report.confidence != null && (
        <span className="text-slate-500">{(report.confidence * 100).toFixed(0)}%</span>
      )}
      {report.summary && (
        <span className="text-slate-500 truncate max-w-xs">{report.summary}</span>
      )}
      {expanded && report.reasoning && (
        <span className="basis-full text-slate-400 leading-snug">{report.reasoning}</span>
      )}
    </StageRow>
  );
}

function DebateRow({ debate, expanded }: { debate?: DebateResult | null; expanded?: boolean }) {
  if (!debate) {
    return (
      <StageRow label="S2 DEBATE">
        <span className="text-slate-600 italic text-xs">not captured — snapshot pending</span>
      </StageRow>
    );
  }
  const bull = debate.bull_score ?? 0;
  const bear = debate.bear_score ?? 0;
  const score = debate.debate_score ?? 0;
  return (
    <StageRow label="S2 DEBATE">
      <span className={`font-mono font-semibold ${verdictColor(debate.verdict)}`}>
        {debate.verdict ?? "UNKNOWN"}
      </span>
      <span className="text-slate-500">
        Bull <span className="text-emerald-400">{bull.toFixed(1)}</span>
        {" / "}
        Bear <span className="text-red-400">{bear.toFixed(1)}</span>
      </span>
      <span className={`font-mono ${score >= 0 ? "text-emerald-400" : "text-red-400"}`}>
        score {score >= 0 ? "+" : ""}{score.toFixed(2)}
      </span>
      {debate.rounds_completed != null && (
        <span className="text-slate-600">{debate.rounds_completed} rounds</span>
      )}
      {expanded && debate.bull_weakest_point && (
        <span className="basis-full text-slate-400 leading-snug">
          <span className="text-emerald-600">bull weak pt:</span> {debate.bull_weakest_point}
        </span>
      )}
      {expanded && debate.bear_weakest_point && (
        <span className="basis-full text-slate-400 leading-snug">
          <span className="text-red-600">bear weak pt:</span> {debate.bear_weakest_point}
        </span>
      )}
    </StageRow>
  );
}

interface DecisionCardProps {
  decision: RecentPipelineDecision;
}

function DecisionCard({ decision }: DecisionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const snap: PipelineDecisionSnapshot | undefined = decision.pipeline_snapshot;
  const td = snap?.trade_decision;
  const rd = snap?.risk_decision;
  const fd = snap?.fund_decision;
  const ar = snap?.analyst_reports;
  const conviction = fd?.final_conviction ?? snap?.boosted_confidence ?? snap?.confidence;
  const hasNarrative = Boolean(
    snap &&
      (td?.reasoning ||
        rd?.reasoning ||
        snap.debate_result?.bull_weakest_point ||
        ar?.technical?.reasoning ||
        ar?.news?.reasoning ||
        ar?.social?.reasoning ||
        ar?.fundamental?.reasoning)
  );

  return (
    <div className="border border-cyan-900/40 bg-slate-950 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-slate-900/50">
        <div className="flex items-center gap-3">
          {hasNarrative && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse reasoning" : "Expand full reasoning"}
              className="text-slate-500 hover:text-cyan-400 transition-colors"
            >
              {expanded ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
            </button>
          )}
          <span className="text-slate-300 font-mono font-bold text-sm tracking-wider">
            {decision.symbol}
          </span>
          <span className={`font-mono font-bold text-sm uppercase ${actionColor(decision.action)}`}>
            {decision.action}
          </span>
          {decision.entry_price != null && (
            <span className="text-slate-400 text-sm font-mono">
              @ ${decision.entry_price.toFixed(2)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {conviction != null && (
            <span className="text-xs text-slate-400">
              conviction{" "}
              <span className="text-cyan-400 font-mono">{(conviction * 100).toFixed(0)}%</span>
            </span>
          )}
          <span
            className={`text-xs px-1.5 py-0.5 rounded font-mono uppercase ${
              decision.status === "approved"
                ? "bg-emerald-950 text-emerald-400"
                : decision.status === "rejected"
                ? "bg-red-950 text-red-400"
                : "bg-slate-800 text-slate-400"
            }`}
          >
            {decision.status}
          </span>
          <span className="text-xs text-slate-600">{timeAgo(decision.created_at)}</span>
        </div>
      </div>

      {/* Pipeline stages */}
      {snap ? (
        <div className="px-3 py-2 space-y-0.5">
          {/* Stage 1 — Analysts */}
          <AnalystRow name="TECH" report={ar?.technical} expanded={expanded} />
          <AnalystRow name="NEWS" report={ar?.news} expanded={expanded} />
          <AnalystRow name="SOCIAL" report={ar?.social} expanded={expanded} />
          <AnalystRow name="MACRO" report={ar?.fundamental} expanded={expanded} />

          {/* Divider */}
          <div className="border-t border-slate-800/60 my-1" />

          {/* Stage 2 — Debate */}
          <DebateRow debate={snap.debate_result} expanded={expanded} />

          {/* Stage 3 — Trade Decision */}
          <StageRow label="S3 TRADER" approved={decision.action !== "hold" ? true : null}>
            {td ? (
              <>
                <span className={`font-mono font-semibold ${actionColor(td.action ?? decision.action)}`}>
                  {(td.action ?? decision.action).toUpperCase()}
                </span>
                {td.stop_price != null && td.limit_price != null && (
                  <span className="text-slate-400 font-mono text-xs">
                    ${td.limit_price.toFixed(2)} &#8594; stop ${td.stop_price.toFixed(2)}
                    {td.target_price != null && (
                      <> &#8594; T1 ${td.target_price.toFixed(2)}</>
                    )}
                  </span>
                )}
                {expanded && td.reasoning && (
                  <span className="basis-full text-slate-400 leading-snug">{td.reasoning}</span>
                )}
              </>
            ) : (
              <span className="text-slate-600">no trade decision data</span>
            )}
          </StageRow>

          {/* Stage 4 — Risk */}
          <StageRow label="S4 RISK" approved={rd?.approved ?? null}>
            {rd ? (
              <>
                <span className={rd.approved ? "text-emerald-400" : "text-red-400"}>
                  {rd.approved ? "APPROVED" : "VETOED"}
                </span>
                {rd.reasoning && (
                  <span
                    className={`text-slate-500 ${expanded ? "basis-full leading-snug" : "truncate max-w-xs"}`}
                  >
                    {rd.reasoning}
                  </span>
                )}
              </>
            ) : (
              <span className="text-slate-600">no risk data</span>
            )}
          </StageRow>

          {/* Stage 5 — Fund Manager */}
          <StageRow label="S5 FUND" approved={fd?.approved ?? null}>
            {fd ? (
              <>
                <span className={fd.approved ? "text-emerald-400" : "text-red-400"}>
                  {fd.approved ? "APPROVED" : "VETOED"}
                </span>
                {fd.final_conviction != null && (
                  <span className="text-slate-400 font-mono">
                    conviction {(fd.final_conviction * 100).toFixed(0)}%
                  </span>
                )}
                {fd.reasoning && (
                  <span className="text-slate-600 truncate max-w-xs text-xs">{fd.reasoning}</span>
                )}
              </>
            ) : (
              <span className="text-slate-600">no fund manager data</span>
            )}
          </StageRow>

          {/* Summary */}
          {snap.summary && (
            <>
              <div className="border-t border-slate-800/60 my-1" />
              <div className="text-xs text-slate-500 italic px-1">{snap.summary}</div>
            </>
          )}
        </div>
      ) : (
        <div className="px-3 py-3 text-xs text-slate-600 italic">
          Reasoning data not captured for this trade. Future trades will show full pipeline breakdown.
        </div>
      )}
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export default function LiveTradeReasoningWidget() {
  const { data, error, isLoading } = useSWR<RecentPipelineReasoningResponse>(
    "/pipeline/recent-with-reasoning?limit=5",
    (url: string) => fetchEngine<RecentPipelineReasoningResponse>(url),
    { refreshInterval: 30_000 }
  );

  return (
    <div className="rounded-xl border border-cyan-900/30 bg-slate-900/50 backdrop-blur p-4">
      {/* Widget header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-cyan-300 tracking-widest uppercase">
            Pipeline Reasoning
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            How &amp; why each trade decision was made
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!error && !isLoading && (
            <span className="text-xs text-slate-600">auto-refresh 30s</span>
          )}
          {isLoading && (
            <span className="text-xs text-slate-600 animate-pulse">loading...</span>
          )}
          {error && (
            <span className="text-xs text-red-500">engine offline</span>
          )}
        </div>
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-24 bg-slate-800/50 rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {/* Error state */}
      {!isLoading && error && (
        <div className="border border-red-900/40 rounded-lg p-3 text-xs text-red-400">
          Cannot fetch pipeline decisions — engine not responding through the dashboard proxy
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && (!data?.decisions || data.decisions.length === 0) && (
        <div className="border border-slate-800 rounded-lg p-4 text-center">
          <p className="text-slate-500 text-sm">No pipeline decisions yet</p>
          <p className="text-slate-600 text-xs mt-1">
            Scanner fires every 60 min during Globex hours (MCL + MNQ)
          </p>
        </div>
      )}

      {/* Decision cards */}
      {!isLoading && !error && data?.decisions && data.decisions.length > 0 && (
        <div className="space-y-3">
          {data.decisions.map((d) => (
            <DecisionCard key={d.approval_id} decision={d} />
          ))}
        </div>
      )}
    </div>
  );
}
