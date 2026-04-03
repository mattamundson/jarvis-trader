"use client";

interface PipelineEntry {
  timestamp?: string;
  symbol?: string;
  final_action?: string;
  confidence?: number;
  technical_score?: number;
  debate_winner?: string;
  risk_verdict?: string;
  regime?: string;
  reasoning?: string;
  error?: string;
}

interface Props {
  latestRun?: PipelineEntry | null;
  isLoading?: boolean;
}

const STAGES = [
  { id: "technical", label: "TECHNICAL", subtitle: "Analysis" },
  { id: "debate", label: "DEBATE", subtitle: "Bull/Bear" },
  { id: "decision", label: "DECISION", subtitle: "Trade Maker" },
  { id: "risk", label: "RISK", subtitle: "Review" },
  { id: "fund", label: "FUND MGR", subtitle: "Execute" },
];

export function PipelineFlowDiagram({ latestRun, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-4 text-center">
        <div className="text-slate-500 font-mono text-sm">Loading pipeline status...</div>
      </div>
    );
  }

  const stageData: Record<string, { value: string; color: string }> = {};

  if (latestRun) {
    stageData.technical = {
      value: latestRun.technical_score != null ? `Score: ${(latestRun.technical_score * 100).toFixed(0)}%` : "—",
      color: (latestRun.technical_score ?? 0) >= 0.5 ? "#00ff88" : "#64748b",
    };
    stageData.debate = {
      value: latestRun.debate_winner ?? "—",
      color: latestRun.debate_winner === "BULL" ? "#00ff88" : latestRun.debate_winner === "BEAR" ? "#ff4466" : "#64748b",
    };
    stageData.decision = {
      value: latestRun.final_action ?? "—",
      color: latestRun.final_action === "BUY" ? "#00ff88" : latestRun.final_action === "SELL" ? "#ff4466" : "#64748b",
    };
    stageData.risk = {
      value: latestRun.risk_verdict ?? "—",
      color: latestRun.risk_verdict === "APPROVED" ? "#00ff88" : latestRun.risk_verdict === "REJECTED" ? "#ff4466" : "#64748b",
    };
    stageData.fund = {
      value: latestRun.final_action === "BUY" && latestRun.risk_verdict === "APPROVED" ? "EXECUTE" : "HOLD",
      color: latestRun.final_action === "BUY" && latestRun.risk_verdict === "APPROVED" ? "#00ff88" : "#64748b",
    };
  }

  const isActive = !!latestRun && !latestRun.error;

  return (
    <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs font-mono text-cyan-400 tracking-widest">5-STAGE PIPELINE</div>
        {latestRun?.timestamp && (
          <div className="text-[10px] font-mono text-slate-600">
            Last run: {new Date(latestRun.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}
          </div>
        )}
      </div>

      {!latestRun ? (
        <div className="text-slate-600 font-mono text-xs text-center py-4">
          No pipeline runs recorded — engine may be idle
        </div>
      ) : (
        <>
          {/* Flow diagram */}
          <div className="flex items-center gap-1 overflow-x-auto pb-2">
            {STAGES.map((stage, i) => {
              const d = stageData[stage.id];
              return (
                <div key={stage.id} className="flex items-center gap-1 shrink-0">
                  <div
                    className="border rounded p-2 min-w-[90px] text-center"
                    style={{
                      borderColor: d?.color ?? "rgba(0,212,255,0.2)",
                      backgroundColor: d?.color ? `${d.color}15` : "rgba(0,0,0,0.3)",
                    }}
                  >
                    <div className="text-[9px] font-mono text-slate-500 tracking-widest">{stage.label}</div>
                    <div className="text-[9px] font-mono text-slate-600 mb-1">{stage.subtitle}</div>
                    <div
                      className="text-xs font-mono font-bold"
                      style={{ color: d?.color ?? "#64748b" }}
                    >
                      {d?.value ?? "—"}
                    </div>
                  </div>
                  {i < STAGES.length - 1 && (
                    <div
                      className="text-lg shrink-0"
                      style={{ color: isActive ? "rgba(0,212,255,0.4)" : "rgba(100,116,139,0.3)" }}
                    >
                      →
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Summary row */}
          <div className="mt-3 pt-3 border-t border-cyan-900/20 flex items-center gap-4 text-[10px] font-mono">
            {latestRun.symbol && (
              <span className="text-slate-500">Symbol: <span className="text-white">{latestRun.symbol}</span></span>
            )}
            {latestRun.confidence != null && (
              <span className="text-slate-500">
                Confidence: <span className="text-white">{(latestRun.confidence * 100).toFixed(0)}%</span>
              </span>
            )}
            {latestRun.regime && (
              <span className="text-slate-500">Regime: <span className="text-white">{latestRun.regime}</span></span>
            )}
            <span
              className="ml-auto font-bold"
              style={{
                color:
                  latestRun.final_action === "BUY"
                    ? "#00ff88"
                    : latestRun.final_action === "SELL"
                    ? "#ff4466"
                    : "#64748b",
              }}
            >
              FINAL: {latestRun.final_action ?? "—"}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
