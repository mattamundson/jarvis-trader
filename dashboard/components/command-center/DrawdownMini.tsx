"use client";
import dynamic from "next/dynamic";

const DrawdownChart = dynamic(
  () =>
    import("@/components/DrawdownChart").then((m) => ({
      default: m.DrawdownChart,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-32 bg-slate-950/40 animate-pulse rounded" />
    ),
  }
);

export function DrawdownMini() {
  return (
    <div className="bg-slate-900/60 border border-cyan-900/40 rounded-lg overflow-hidden">
      <div className="px-3 py-2 border-b border-cyan-900/20">
        <span className="text-[10px] font-mono text-cyan-400 tracking-widest">
          DRAWDOWN
        </span>
      </div>
      <div className="p-2">
        <DrawdownChart />
      </div>
    </div>
  );
}
