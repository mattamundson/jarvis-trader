"use client";
import dynamic from "next/dynamic";

const EquityCurveWidget = dynamic(
  () =>
    import("@/components/EquityCurveWidget").then((m) => ({
      default: m.EquityCurveWidget,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-32 bg-slate-950/40 animate-pulse rounded" />
    ),
  }
);

export function EquityCurveMini() {
  return (
    <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg overflow-hidden">
      <div className="px-3 py-2 border-b border-cyan-900/20">
        <span className="text-[10px] font-mono text-cyan-400 tracking-widest">
          EQUITY CURVE
        </span>
      </div>
      <div className="p-2">
        <EquityCurveWidget />
      </div>
    </div>
  );
}
