import type { OpsSnapshot } from "@/lib/ops/snapshot";
import { JournalPanel } from "./Journal";
import { LadderPanel } from "./Ladder";
import { LockoutPanel } from "./Lockout";
import { StrikePanel } from "./Strikes";
import { Pill, MONO } from "./ui";

/** Read-only ops board. Server component: no client JS, no polling, no writes, nothing sent anywhere. */
export function OpsView({ snapshot: s }: { snapshot: OpsSnapshot }) {
  return (
    <div className="min-h-screen bg-background px-3 py-3 text-foreground" data-testid="ops-root">
      <div className="mx-auto max-w-[1500px] space-y-2">
        <header className="flex flex-wrap items-center justify-between gap-2 rounded border border-border px-3 py-2">
          <div>
            <h1 className="text-sm font-semibold uppercase tracking-wider">Ops · Hermes record</h1>
            <p className="text-[11px] text-muted-foreground">Public, read-only. Paper and record-keeping only. Account ids are masked to the last 4.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone="bear">Live legal? NO</Pill><Pill tone="bear">size 0</Pill><Pill tone="muted">public read-only</Pill>
            <span className={`text-[10px] text-muted-foreground ${MONO}`}>source: {s.dir ?? "none found"} · built {s.generatedIso.slice(0, 16).replace("T", " ")}Z</span>
          </div>
        </header>

        {s.warnings.length > 0 && (
          <ul className="space-y-0.5 rounded border border-warn/50 px-3 py-2 text-xs text-warn" data-testid="ops-warnings">
            {s.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
          </ul>
        )}

        <div className="grid grid-cols-12 gap-2">
          <div className="col-span-12 space-y-2 xl:col-span-7"><LadderPanel s={s} /><JournalPanel s={s} /></div>
          <div className="col-span-12 space-y-2 xl:col-span-5"><LockoutPanel s={s} /><StrikePanel s={s} /></div>
        </div>

        <footer className={`flex flex-wrap gap-x-4 gap-y-1 px-1 text-[10px] text-muted-foreground ${MONO}`}>
          {s.files.map((f) => (
            <span key={f.key} className={f.found ? (f.stale ? "text-warn" : "") : "text-bear"}>
              {f.name}: {f.found ? `${f.ageHours}h old` : "missing"}
            </span>
          ))}
        </footer>
      </div>
    </div>
  );
}
