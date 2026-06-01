import type { DomainStatus } from "@/lib/masterApi";

export function DomainTile({ s }: { s: DomainStatus }) {
  const tone = s.ok ? "border-emerald-500" : s.error ? "border-red-500" : "border-zinc-600";
  return (
    <div className={`rounded-xl border-2 ${tone} bg-zinc-900 p-4`}>
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
    </div>
  );
}
