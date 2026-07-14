"use client";

import type { RegimeStatusResult } from "@/lib/api";

interface RegimeTimelineProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  regime?: RegimeStatusResult | any[] | null;
}

const REGIME_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  TRENDING: {
    bg: "rgba(0,255,136,0.15)",
    border: "rgba(0,255,136,0.4)",
    text: "#00ff88",
  },
  RANGING: {
    bg: "rgba(0,212,255,0.15)",
    border: "rgba(0,212,255,0.4)",
    text: "#00d4ff",
  },
  VOLATILE: {
    bg: "rgba(255,68,102,0.15)",
    border: "rgba(255,68,102,0.4)",
    text: "#ff4466",
  },
};

const DEFAULT_COLOR = {
  bg: "rgba(71,85,105,0.15)",
  border: "rgba(71,85,105,0.4)",
  text: "#475569",
};

export function RegimeTimeline({ regime }: RegimeTimelineProps) {
  // ── Empty state ─────────────────────────────────────────────────────────
  if (!regime || (Array.isArray(regime) && regime.length === 0)) {
    return (
      <div
        className="w-full px-4 py-2 flex items-center"
        style={{ borderTop: "1px solid rgba(0,212,255,0.06)" }}
      >
        <span className="text-[10px] font-mono text-slate-700 tracking-widest">
          REGIME — awaiting data
        </span>
      </div>
    );
  }

  // ── Legacy array shape ──────────────────────────────────────────────────
  if (Array.isArray(regime)) {
    const last = regime[regime.length - 1];
    const regimeStr: string = last?.regime ?? "—";
    const colors = REGIME_COLORS[regimeStr] ?? DEFAULT_COLOR;

    return (
      <div
        className="w-full px-4 py-2 flex items-center gap-3"
        style={{ borderTop: "1px solid rgba(0,212,255,0.06)" }}
      >
        <span className="text-[10px] font-mono text-slate-600 tracking-widest">
          REGIME
        </span>
        <span
          className="text-[10px] font-mono px-2 py-0.5 rounded border font-bold tracking-wider"
          style={{
            background: colors.bg,
            borderColor: colors.border,
            color: colors.text,
          }}
        >
          {regimeStr}
        </span>
        <span className="text-[10px] font-mono text-slate-700 ml-auto">
          {regime.length} pts
        </span>
      </div>
    );
  }

  // ── RegimeStatusResult object shape ─────────────────────────────────────
  const result = regime as RegimeStatusResult;
  const current = result.current_regime ?? "—";
  const currentColors = REGIME_COLORS[current] ?? DEFAULT_COLOR;
  const breakdown = result.regime_breakdown ?? {};
  const total = Object.values(breakdown).reduce((s, v) => s + v, 0) || 1;

  const REGIMES = ["TRENDING", "RANGING", "VOLATILE"] as const;

  return (
    <div
      className="w-full px-3 py-2"
      style={{ borderTop: "1px solid rgba(0,212,255,0.06)" }}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-mono text-slate-600 tracking-widest">
          REGIME
        </span>
        <span
          className="text-[10px] font-mono px-2 py-0.5 rounded border font-bold tracking-wider"
          style={{
            background: currentColors.bg,
            borderColor: currentColors.border,
            color: currentColors.text,
          }}
        >
          {current}
        </span>

        {/* Adaptive STC thresholds */}
        {(result.adaptive_stc_os != null || result.adaptive_stc_ob != null) && (
          <span className="text-[10px] font-mono text-slate-600 ml-auto">
            STC OS:{result.adaptive_stc_os ?? "—"} OB:{result.adaptive_stc_ob ?? "—"}
          </span>
        )}
      </div>

      {/* Proportional breakdown bar */}
      {Object.keys(breakdown).length > 0 && (
        <div
          className="flex w-full h-2 rounded overflow-hidden"
          style={{ gap: "1px" }}
        >
          {REGIMES.map((r) => {
            const pct = ((breakdown[r] ?? 0) / total) * 100;
            if (pct < 1) return null;
            const c = REGIME_COLORS[r] ?? DEFAULT_COLOR;
            return (
              <div
                key={r}
                title={`${r}: ${pct.toFixed(0)}%`}
                style={{
                  width: `${pct}%`,
                  background: c.bg,
                  borderTop: `1px solid ${c.border}`,
                  borderBottom: `1px solid ${c.border}`,
                }}
              />
            );
          })}
        </div>
      )}

      {/* Breakdown labels */}
      {Object.keys(breakdown).length > 0 && (
        <div className="flex items-center gap-3 mt-1">
          {REGIMES.map((r) => {
            const pct = ((breakdown[r] ?? 0) / total) * 100;
            const c = REGIME_COLORS[r] ?? DEFAULT_COLOR;
            return (
              <span key={r} className="text-[9px] font-mono" style={{ color: c.text }}>
                {r.charAt(0)}: {pct.toFixed(0)}%
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
