"use client";
import useSWR from "swr";
import {
  fetchMasterSchedulerRuns,
  fetchMasterSchedulerStatus,
  type SchedulerRun,
} from "@/lib/masterApi";

function runTone(status: string): string {
  switch (status) {
    case "ok":
      return "text-emerald-400";
    case "degraded":
      return "text-amber-400";
    case "error":
      return "text-red-400";
    case "skipped":
      return "text-zinc-400";
    default:
      return "text-zinc-300";
  }
}

function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
}

export function SchedulerPanel() {
  const { data: status, error: statusErr } = useSWR(
    "master-scheduler-status",
    fetchMasterSchedulerStatus,
    { refreshInterval: 15000 },
  );
  const { data: runsData, error: runsErr } = useSWR(
    "master-scheduler-runs",
    () => fetchMasterSchedulerRuns(8),
    { refreshInterval: 15000 },
  );

  // Both failing => the scheduler endpoints aren't deployed yet. Degrade quietly
  // instead of sinking the surrounding page (its own SWR is independent).
  const unavailable = Boolean(statusErr && runsErr);

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-lg font-semibold text-zinc-100">Scheduler</h2>
        {status ? (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              status.running
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-zinc-700 text-zinc-300"
            }`}
          >
            {status.running ? "running" : "idle"}
          </span>
        ) : null}
      </div>

      {unavailable ? (
        <div className="rounded-xl border-2 border-zinc-700 bg-zinc-900 p-4 text-sm text-zinc-400">
          Scheduler endpoints unavailable — deploy the master-api scheduler build, then set
          <code className="mx-1 rounded bg-zinc-800 px-1">SCHEDULER_AUTOSTART=true</code>
          to populate this panel.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-xl border-2 border-zinc-700 bg-zinc-900 p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-300">
              Jobs
            </h3>
            {!status ? (
              <p className="text-sm text-zinc-500">Loading…</p>
            ) : status.jobs.length === 0 ? (
              <p className="text-sm text-zinc-500">No jobs registered.</p>
            ) : (
              <ul className="space-y-2">
                {status.jobs.map((j) => (
                  <li
                    key={j.name}
                    className="flex items-center justify-between text-sm"
                  >
                    <div>
                      <span className="font-medium text-zinc-100">{j.name}</span>
                      <span className="ml-2 text-xs text-zinc-500">
                        every {j.interval_s}s · {j.tier}
                      </span>
                    </div>
                    <span
                      className={`text-xs font-medium ${runTone(j.last_status ?? "")}`}
                    >
                      {j.last_status ?? "—"} · {fmtTime(j.last_run)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border-2 border-zinc-700 bg-zinc-900 p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-300">
              Recent runs
            </h3>
            {!runsData ? (
              <p className="text-sm text-zinc-500">Loading…</p>
            ) : runsData.runs.length === 0 ? (
              <p className="text-sm text-zinc-500">No runs recorded yet.</p>
            ) : (
              <ul className="space-y-2">
                {runsData.runs.map((r: SchedulerRun) => (
                  <li key={r.id} className="text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-zinc-200">{r.job}</span>
                      <span className={`text-xs font-medium ${runTone(r.status)}`}>
                        {r.status}
                        {r.duration_ms != null ? ` · ${r.duration_ms}ms` : ""}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-zinc-500">
                      <span className="truncate pr-2">{r.detail ?? ""}</span>
                      <span className="shrink-0">{fmtTime(r.started_ts)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
