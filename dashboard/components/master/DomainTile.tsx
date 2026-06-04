import type { DomainStatus } from "@/lib/masterApi";

/**
 * Domain summary tile. Pass `interactive` for domains that have a drill-down
 * page (trading, finances) so they advertise it; non-interactive tiles render
 * as plain status cards so they can't be mistaken for having a detail view.
 */
export function DomainTile({ s, interactive = false }: { s: DomainStatus; interactive?: boolean }) {
  const tone = s.ok ? "border-emerald-500" : s.error ? "border-red-500" : "border-zinc-600";
  return (
    <div
      className={`rounded-xl border-2 ${tone} bg-zinc-900 p-4 ${
        interactive ? "transition-colors hover:border-cyan-400" : ""
      }`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          {s.domain}
        </h3>
        <span className={`h-2 w-2 rounded-full ${s.ok ? "bg-emerald-400" : "bg-zinc-500"}`} />
      </div>
      <p className="mt-2 text-sm text-zinc-100">{s.summary}</p>
      {s.alerts.length > 0 && (
        <ul className="mt-2 space-y-1">
          {s.alerts.map((a) => (
            <li key={a} className="text-xs font-medium text-red-400">⚠ {a}</li>
          ))}
        </ul>
      )}
      {interactive && (
        <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-cyan-400">
          View detail →
        </p>
      )}
    </div>
  );
}
