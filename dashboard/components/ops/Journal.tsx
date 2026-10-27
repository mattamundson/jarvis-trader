import type { OpsSnapshot } from "@/lib/ops/snapshot";
import { Missing, Panel, Pill, MONO } from "./ui";

export function JournalPanel({ s }: { s: OpsSnapshot }) {
  const j = s.journal;
  if (!j) return <Panel title="Paper journal" testId="ops-journal"><Missing what="paper-journal.md" /></Panel>;
  return (
    <Panel title="Paper journal" testId="ops-journal" right={<span className="text-[10px] text-muted-foreground">{j.total} rows · {j.liveReviews} live-review rows · last {j.lastDate ?? "n/a"}</span>}>
      <div className="max-h-[520px] overflow-auto">
        <table className={`w-full text-left text-[11px] ${MONO}`}>
          <thead className="sticky top-0 bg-card text-muted-foreground"><tr><th className="pr-3">Date</th><th className="pr-3">Session</th><th className="pr-3">Bias</th><th className="pr-3">Result / R</th><th>Notes</th></tr></thead>
          <tbody>
            {j.recent.map((r, i) => (
              <tr key={i} className="border-t border-border align-top">
                <td className="py-1 pr-3 whitespace-nowrap">{r.date}</td>
                <td className="pr-3">{r.live && <Pill tone="warn">live</Pill>} {r.session}</td>
                <td className="pr-3">{r.bias}</td>
                <td className="pr-3 whitespace-nowrap">{r.rResult && r.rResult !== "—" ? r.rResult : r.result}</td>
                <td className="text-muted-foreground">{r.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
