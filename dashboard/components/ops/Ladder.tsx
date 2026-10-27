import type { OpsSnapshot } from "@/lib/ops/snapshot";
import { Missing, Panel, Pill, Stat, MONO } from "./ui";

const fmtR = (r: number | null) => (r === null ? "n/a" : `${r > 0 ? "+" : ""}${r.toFixed(2)}R`);

export function LadderPanel({ s }: { s: OpsSnapshot }) {
  const b = s.ladder;
  if (!b) return <Panel title="Hermes ladder" testId="ops-ladder"><Missing what="rebuild-ladder-tracker.md" /></Panel>;
  const l = b.ladder;
  return (
    <Panel title="Hermes ladder" testId="ops-ladder" right={l.sessionLogThrough ? <span className="text-[10px] text-muted-foreground">session log through {l.sessionLogThrough}</span> : undefined}>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat label="Clean sessions (step 2)" value={l.cleanSessions ? `${l.cleanSessions.done} / ${l.cleanSessions.target}` : "n/a"} tone={l.cleanSessions && l.cleanSessions.done >= l.cleanSessions.target ? "bull" : "warn"} />
        <Stat label="Running clean (to 20)" value={l.runningClean ? `${l.runningClean.n} / ${l.runningClean.of}` : "n/a"} tone="warn" sub="needed before 1R options" />
        <Stat label="Scored setups" value={l.scored ? `${l.scored.n} / ${l.scored.of}` : "n/a"} tone="warn" sub={s.scoredCsv ? `scored-setups.csv rows: ${s.scoredCsv.rows}` : undefined} />
        <Stat label="Avg R (approx.)" value={fmtR(l.scored?.avgR ?? null)} tone={l.scored?.avgR != null && l.scored.avgR > 0 ? "bull" : "warn"} sub="paper, delayed data; not P&L" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <Pill tone="bear">Live legal? NO</Pill><Pill tone="bear">size 0</Pill>
        {l.strikes30d !== null && <Pill tone="bear">{l.strikes30d} strikes / 30d</Pill>}
        {l.liveStatus && <span className="text-muted-foreground">{l.liveStatus}</span>}
      </div>
      {l.step && <p className="mt-2 text-xs text-muted-foreground"><span className="uppercase tracking-wider">Step:</span> {l.step}</p>}

      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wider text-muted-foreground">Go-live checklist ({b.unlock.filter((u) => u.done).length}/{b.unlock.length} done)</h3>
      <ul className="space-y-1 text-xs">
        {b.unlock.map((u, i) => (
          <li key={i} className="flex gap-2"><span className={u.done ? "text-bull" : "text-muted-foreground"}>{u.done ? "[x]" : "[ ]"}</span><span>{u.text}</span></li>
        ))}
      </ul>

      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wider text-muted-foreground">Recent sessions ({b.sessionCount} logged)</h3>
      <div className="overflow-x-auto">
        <table className={`w-full text-left text-[11px] ${MONO}`}>
          <thead className="text-muted-foreground"><tr><th className="pr-3">Date</th><th className="pr-3">Bias</th><th className="pr-3">Verdict</th><th>Rule breaks</th></tr></thead>
          <tbody>
            {b.recentSessions.map((r) => (
              <tr key={r.date} className="border-t border-border align-top">
                <td className="py-1 pr-3 whitespace-nowrap">{r.date}</td><td className="pr-3">{r.bias}</td>
                <td className="pr-3 whitespace-nowrap"><Pill tone={r.verdict === "clean" ? "bull" : r.verdict === "not clean" ? "bear" : "muted"}>{r.verdict}</Pill></td>
                <td className="text-muted-foreground">{r.ruleBreaks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
