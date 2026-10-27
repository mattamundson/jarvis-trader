import type { OpsSnapshot } from "@/lib/ops/snapshot";
import { Missing, Panel, Pill, MONO } from "./ui";

export function StrikePanel({ s }: { s: OpsSnapshot }) {
  const k = s.strikes;
  if (!k) return <Panel title="Strike log" testId="ops-strikes"><Missing what="strike-log.md" /></Panel>;
  return (
    <Panel title="Strike log" testId="ops-strikes" right={k.countUpdated ? <span className="text-[10px] text-muted-foreground">count updated {k.countUpdated}</span> : undefined}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <Pill tone="bear">{k.confirmedCount ?? "?"} confirmed (30d)</Pill>
        {k.pending.length > 0 && <Pill tone="warn">{k.pending.length} pending Matt&apos;s yes</Pill>}
      </div>
      {k.countNote && <p className="mb-2 text-[11px] text-muted-foreground">{k.countNote}</p>}
      <div className="max-h-[420px] overflow-auto">
        <table className={`w-full text-left text-[11px] ${MONO}`}>
          <thead className="sticky top-0 bg-card text-muted-foreground"><tr><th className="pr-2">#</th><th className="pr-3">Date</th><th className="pr-3">Bans broken</th><th>Status</th></tr></thead>
          <tbody>
            {k.pending.map((r) => (
              <tr key={r.id} className="border-t border-border align-top"><td className="py-1 pr-2 text-warn">{r.id}</td><td className="pr-3 whitespace-nowrap">{r.date}</td><td className="pr-3 text-muted-foreground">{r.bans}</td><td className="text-warn">{r.status || "pending"}</td></tr>
            ))}
            {[...k.confirmed].sort((a, b) => (a.date < b.date ? 1 : -1)).map((r) => (
              <tr key={r.id} className="border-t border-border align-top"><td className="py-1 pr-2">{r.id}</td><td className="pr-3 whitespace-nowrap">{r.date}</td><td className="pr-3 text-muted-foreground">{r.bans}</td><td className="text-muted-foreground">{r.status}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
