"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetcher, LoadingRows, relativeTime, UnreachableNote } from "./shared";

// GET /pipeline/status — engine/routers/pipeline_router.py pipeline_status()
interface PipelineStatusLive {
  available: boolean;
  sdk_available: boolean;
  last_run: Record<string, unknown> | null;
  decision_count: number;
}

// GET /decisions/recent — rows from SQLite decisions table (defensive shape;
// field names vary between the DB rows and the in-memory ring buffer).
interface DecisionRow {
  id?: number | string;
  symbol?: string;
  action?: string;
  final_action?: string;
  direction?: string;
  confidence?: number;
  conviction?: number;
  timestamp?: string;
  created_at?: string;
}

// GET /scheduler/status — engine/routers/scheduler_router.py
interface SchedulerJob {
  id: string;
  name: string;
  next_run: string | null;
}

interface SchedulerStatusLive {
  running: boolean;
  jobs: SchedulerJob[];
  total_decisions_logged?: number;
}

function normalizeDirection(d: DecisionRow): "LONG" | "SHORT" | "HOLD" {
  const raw = (d.direction ?? d.action ?? d.final_action ?? "HOLD").toString().toUpperCase();
  if (raw === "LONG" || raw === "BUY") return "LONG";
  if (raw === "SHORT" || raw === "SELL") return "SHORT";
  return "HOLD";
}

function lastDecisionPerSymbol(rows: DecisionRow[]): DecisionRow[] {
  const bySymbol = new Map<string, DecisionRow>();
  for (const row of rows) {
    const sym = row.symbol?.toUpperCase();
    if (!sym) continue;
    const ts = new Date(row.timestamp ?? row.created_at ?? 0).getTime();
    const prev = bySymbol.get(sym);
    const prevTs = prev ? new Date(prev.timestamp ?? prev.created_at ?? 0).getTime() : -1;
    if (!prev || ts > prevTs) bySymbol.set(sym, row);
  }
  return Array.from(bySymbol.values()).sort((a, b) =>
    (a.symbol ?? "").localeCompare(b.symbol ?? "")
  );
}

function nextScan(jobs: SchedulerJob[] | undefined): SchedulerJob | null {
  if (!jobs || jobs.length === 0) return null;
  const upcoming = jobs
    .filter((j) => j.next_run != null)
    .sort((a, b) => new Date(a.next_run!).getTime() - new Date(b.next_run!).getTime());
  // Prefer the soonest scan-like job; fall back to the soonest job of any kind.
  const scanJob = upcoming.find((j) => /scan/i.test(`${j.id} ${j.name}`));
  return scanJob ?? upcoming[0] ?? null;
}

export function SignalsPipelinePanel() {
  const {
    data: pipeline,
    error: pipelineError,
    isLoading: pipelineLoading,
  } = useSWR<PipelineStatusLive>("/pipeline/status", fetcher, { refreshInterval: POLL_INTERVAL.STATUS });

  const {
    data: decisions,
    error: decisionsError,
    isLoading: decisionsLoading,
  } = useSWR<DecisionRow[]>("/decisions/recent?limit=50", fetcher, { refreshInterval: POLL_INTERVAL.STATUS });

  const { data: scheduler, error: schedulerError } = useSWR<SchedulerStatusLive>(
    "/scheduler/status",
    fetcher,
    { refreshInterval: POLL_INTERVAL.STATUS }
  );

  const perSymbol = lastDecisionPerSymbol(Array.isArray(decisions) ? decisions : []);
  const upcoming = nextScan(scheduler?.jobs);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Signals &amp; Pipeline</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Pipeline availability */}
        {pipelineError ? (
          <UnreachableNote endpoint="/pipeline/status" />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">Pipeline</span>
              <Badge variant={pipeline?.available ? "bull" : "bear"}>
                {pipelineLoading ? "…" : pipeline?.available ? "AVAILABLE" : "UNAVAILABLE"}
              </Badge>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">SDK</span>
              <Badge variant={pipeline?.sdk_available ? "bull" : "neutral"}>
                {pipeline?.sdk_available ? "READY" : "OFF"}
              </Badge>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">Decisions logged</span>
              <span className="font-mono text-xs font-semibold text-foreground">
                {pipeline?.decision_count ?? "—"}
              </span>
            </div>
          </div>
        )}

        {/* Last signal per symbol */}
        {decisionsError ? (
          <UnreachableNote endpoint="/decisions/recent" />
        ) : decisionsLoading ? (
          <LoadingRows rows={3} />
        ) : perSymbol.length === 0 ? (
          <p className="text-xs text-muted-foreground">No recent decisions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-1 pr-3 font-medium">Symbol</th>
                  <th className="py-1 pr-3 font-medium">Signal</th>
                  <th className="py-1 pr-3 font-medium text-right">Conviction</th>
                  <th className="py-1 font-medium text-right">When</th>
                </tr>
              </thead>
              <tbody>
                {perSymbol.map((d) => {
                  const dir = normalizeDirection(d);
                  const conviction = d.conviction ?? d.confidence;
                  return (
                    <tr key={`${d.symbol}-${d.id}`} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5 pr-3 font-semibold">{d.symbol}</td>
                      <td className="py-1.5 pr-3">
                        <Badge variant={dir === "LONG" ? "bull" : dir === "SHORT" ? "bear" : "neutral"}>
                          {dir}
                        </Badge>
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono">
                        {conviction != null ? Number(conviction).toFixed(2) : "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono text-muted-foreground">
                        {relativeTime(d.timestamp ?? d.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Next scheduled scan */}
        <div className="border-t border-border pt-3">
          {schedulerError ? (
            <UnreachableNote endpoint="/scheduler/status" />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-muted-foreground">Scheduler</span>
              <Badge variant={scheduler?.running ? "bull" : "bear"}>
                {scheduler ? (scheduler.running ? "RUNNING" : "STOPPED") : "—"}
              </Badge>
              {upcoming ? (
                <span className="text-[11px] text-muted-foreground">
                  Next: <span className="font-mono text-foreground">{upcoming.name || upcoming.id}</span>{" "}
                  {upcoming.next_run
                    ? `at ${new Date(upcoming.next_run).toLocaleTimeString("en-US", {
                        hour: "2-digit",
                        minute: "2-digit",
                        hour12: false,
                      })}`
                    : ""}
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground">No scheduled jobs.</span>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
