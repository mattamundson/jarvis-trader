import type { OpsSnapshot } from "@/lib/ops/snapshot";
import { Panel, Pill } from "./ui";

export function LockoutPanel({ s }: { s: OpsSnapshot }) {
  const l = s.lockout;
  if (!l) return null;
  const done = l.conditions.filter((c) => c.done).length;
  return (
    <Panel title="Lockout status" testId="ops-lockout" right={<Pill tone={l.on ? "bear" : "warn"}>{l.on ? "Lockout ON" : "Lockout off per record"}</Pill>}>
      <p className="text-sm">{l.summary}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {l.strikeWindow && <Pill tone={l.strikeWindow.phase === "in-window" ? "bear" : "warn"}>strike lockout {l.strikeWindow.from} → {l.strikeWindow.to} ({l.strikeWindow.phase})</Pill>}
        {l.weeklyUnreleased !== null && <Pill tone={l.weeklyUnreleased ? "bear" : "bull"}>weekly 3R: {l.weeklyUnreleased ? "unreleased" : "released"}</Pill>}
        {l.releaseRecords !== null && <Pill tone="muted">release records: {l.releaseRecords}</Pill>}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Agents never lift a lockout. Only Matt&apos;s written yes does, as the last step of the checklist.</p>
      <h3 className="mb-1 mt-3 text-[10px] uppercase tracking-wider text-muted-foreground">Release conditions ({done}/{l.conditions.length} checked)</h3>
      <ul className="space-y-1 text-xs">
        {l.conditions.map((c, i) => (
          <li key={i} className="flex gap-2"><span className={c.done ? "text-bull" : "text-muted-foreground"}>{c.done ? "[x]" : "[ ]"}</span><span><b>{c.label}</b> {c.text}</span></li>
        ))}
      </ul>
    </Panel>
  );
}
