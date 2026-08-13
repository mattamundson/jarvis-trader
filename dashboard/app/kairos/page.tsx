"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import { useState, useCallback } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Eye,
  Radio,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine, postEngine } from "@/lib/api";
import { KairosObservationFeed } from "@/components/KairosObservationFeed";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KairosStatus {
  enabled: boolean;
  running: boolean;
  tick_count: number;
  watcher_count: number;
  last_tick: string | null;
  uptime_seconds: number | null | undefined;
  error_count: number;
}

interface KairosWatcher {
  name: string;
  enabled: boolean;
  hit_count_today: number;
  warning_count_today: number;
  critical_count_today: number;
  last_observation: string | null;
}

interface WatchersResponse {
  watchers: KairosWatcher[];
}

interface DreamSeverityCounts {
  info: number;
  warning: number;
  critical: number;
}

interface DreamTopWatcher {
  watcher: string;
  count: number;
}

interface DreamSummary {
  date: string;
  total_observations: number;
  severity_counts: DreamSeverityCounts;
  top_watchers: DreamTopWatcher[];
  insights: string | null;
  generated_at: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds) || isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch {
    return "unknown";
  }
}

function getYesterdayDateStr(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().split("T")[0];
}

function getTodayDateStr(): string {
  return new Date().toISOString().split("T")[0];
}

// ── Watcher Card ──────────────────────────────────────────────────────────────

function WatcherCard({ watcher }: { watcher: KairosWatcher }) {
  const hasCritical = watcher.critical_count_today > 0;
  const hasWarning = watcher.warning_count_today > 0;

  const borderClass = !watcher.enabled
    ? "border-border bg-muted/30"
    : hasCritical
    ? "border-bear/30 bg-bear/5"
    : hasWarning
    ? "border-warn/30 bg-warn/5"
    : watcher.hit_count_today > 0
    ? "border-bull/20 bg-bull/5"
    : "border-border bg-card";

  const statusVariant: "bull" | "bear" | "warn" | "neutral" = !watcher.enabled
    ? "neutral"
    : hasCritical
    ? "bear"
    : hasWarning
    ? "warn"
    : "bull";

  const statusLabel = !watcher.enabled
    ? "Disabled"
    : hasCritical
    ? "Critical"
    : hasWarning
    ? "Warning"
    : watcher.hit_count_today > 0
    ? "Active"
    : "Quiet";

  return (
    <div className={`rounded-xl border p-3 space-y-2 ${borderClass}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Eye className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <p className="text-xs font-semibold text-foreground truncate">{watcher.name}</p>
        </div>
        <Badge variant={statusVariant}>{statusLabel}</Badge>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
        <span>{watcher.hit_count_today} hits</span>
        {watcher.warning_count_today > 0 && (
          <span className="text-warn">{watcher.warning_count_today} warn</span>
        )}
        {watcher.critical_count_today > 0 && (
          <span className="text-bear">{watcher.critical_count_today} crit</span>
        )}
        <span className="ml-auto">{timeAgo(watcher.last_observation)}</span>
      </div>
    </div>
  );
}

// ── Dream Summary Accordion ───────────────────────────────────────────────────

function DreamAccordion({
  label,
  dream,
  defaultOpen = false,
}: {
  label: string;
  dream: DreamSummary | null | undefined;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-semibold text-foreground">{label}</span>
          {dream && (
            <Badge variant="neutral">{dream.total_observations} obs</Badge>
          )}
        </div>
        {dream?.date && (
          <span className="text-xs text-muted-foreground">{dream.date}</span>
        )}
      </button>

      {open && (
        <div className="p-4 space-y-4 bg-card">
          {!dream ? (
            <p className="text-sm text-muted-foreground text-center py-2">
              No dream summary available for this period.
            </p>
          ) : (
            <>
              {/* Severity breakdown */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Severity Breakdown
                </p>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg bg-info/10 border border-info/20 py-2">
                    <p className="text-info font-semibold text-base font-mono">
                      {dream.severity_counts?.info ?? 0}
                    </p>
                    <p className="text-muted-foreground">Info</p>
                  </div>
                  <div className="rounded-lg bg-warn/10 border border-warn/20 py-2">
                    <p className="text-warn font-semibold text-base font-mono">
                      {dream.severity_counts?.warning ?? 0}
                    </p>
                    <p className="text-muted-foreground">Warning</p>
                  </div>
                  <div className="rounded-lg bg-bear/10 border border-bear/20 py-2">
                    <p className="text-bear font-semibold text-base font-mono">
                      {dream.severity_counts?.critical ?? 0}
                    </p>
                    <p className="text-muted-foreground">Critical</p>
                  </div>
                </div>
              </div>

              {/* Top watchers */}
              {(dream.top_watchers?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Top Watchers
                  </p>
                  <div className="space-y-1">
                    {(dream.top_watchers ?? []).map((tw) => (
                      <div
                        key={tw.watcher}
                        className="flex items-center justify-between text-xs py-1 border-b border-border/50 last:border-0"
                      >
                        <span className="text-foreground font-medium">{tw.watcher}</span>
                        <Badge variant="neutral">{tw.count} hits</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* LLM insights */}
              {dream.insights && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    LLM Insights
                  </p>
                  <div className="rounded-lg bg-muted/40 border border-border p-3">
                    <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono">
                      {dream.insights}
                    </p>
                  </div>
                </div>
              )}

              {dream.generated_at && (
                <p className="text-[11px] text-muted-foreground text-right">
                  Generated {timeAgo(dream.generated_at)}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function KairosPage() {
  const [tickLoading, setTickLoading] = useState(false);
  const [tickResult, setTickResult] = useState<string | null>(null);

  const yesterday = getYesterdayDateStr();
  const today = getTodayDateStr();

  // SWR hooks
  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
    mutate: mutateStatus,
  } = useSWR<KairosStatus>("/kairos/status", fetcher, { refreshInterval: POLL_INTERVAL.SLOW });

  const {
    data: watchersData,
    error: watchersError,
    isLoading: watchersLoading,
  } = useSWR<WatchersResponse>("/kairos/watchers", fetcher, { refreshInterval: POLL_INTERVAL.SLOW });

  const { data: yesterdayDream } = useSWR<DreamSummary>(
    `/kairos/dream/${yesterday}`,
    fetcher,
    { revalidateOnFocus: false }
  );

  const { data: todayDream } = useSWR<DreamSummary>(
    `/kairos/dream/${today}`,
    fetcher,
    { refreshInterval: POLL_INTERVAL.FIVE_MINUTES }
  );

  const watchers = watchersData?.watchers ?? [];

  // Manual tick handler
  const handleManualTick = useCallback(async () => {
    setTickLoading(true);
    setTickResult(null);
    try {
      await postEngine("/kairos/tick");
      setTickResult("Tick triggered successfully");
      mutateStatus();
    } catch (e) {
      setTickResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTickLoading(false);
    }
  }, [mutateStatus]);

  // Disabled state
  const isDisabled = status?.enabled === false;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Dashboard</Link>
              <Link href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Analysis</Link>
              <Link href="/paper" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Paper</Link>
              <Link href="/health" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Health</Link>
              <Link href="/settings" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Settings</Link>
              <Link href="/kairos" className="text-xs text-foreground font-semibold border-b border-accent pb-0.5">KAIROS</Link>
              <Link href="/config" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Config</Link>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {status && (
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  {status.running && status.enabled ? (
                    <>
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-bull" />
                    </>
                  ) : (
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground" />
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  {status.enabled ? (status.running ? "Running" : "Stopped") : "Disabled"}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <ExploratoryBanner what="KAIROS is an experimental monitoring subsystem" />
        {/* Page title */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
              <Radio className="h-6 w-6 text-accent" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-foreground tracking-tight">KAIROS Monitor</h2>
              <p className="text-xs text-muted-foreground">
                Continuous market observation daemon — watchers, observations, and dream summaries
              </p>
            </div>
          </div>

          {/* Status badge */}
          {status && (
            <Badge
              variant={
                !status.enabled ? "neutral" : status.running ? "bull" : "warn"
              }
            >
              <span className="flex items-center gap-1.5">
                {status.enabled && status.running ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : status.enabled ? (
                  <AlertTriangle className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {!status.enabled ? "KAIROS DISABLED" : status.running ? "RUNNING" : "STOPPED"}
              </span>
            </Badge>
          )}
        </div>

        {/* KAIROS disabled banner */}
        {isDisabled && !statusLoading && (
          <div className="rounded-xl border border-warn/30 bg-warn/5 p-6 text-center space-y-2">
            <AlertTriangle className="h-8 w-8 text-warn mx-auto" />
            <p className="text-sm font-semibold text-warn">KAIROS is disabled</p>
            <p className="text-xs text-muted-foreground">
              Enable KAIROS via{" "}
              <Link href="/settings" className="underline text-accent hover:text-accent/80">
                Settings &rsaquo; Feature Flags
              </Link>{" "}
              to start receiving market observations.
            </p>
          </div>
        )}

        {/* Engine unreachable */}
        {statusError && !statusLoading && (
          <div className="rounded-xl border border-bear/30 bg-bear/5 p-6 text-center space-y-2">
            <XCircle className="h-8 w-8 text-bear mx-auto" />
            <p className="text-sm font-semibold text-bear">Engine unreachable</p>
            <p className="text-xs text-muted-foreground">
              Could not fetch /kairos/status — verify the engine is running and the dashboard proxy can reach it.
            </p>
          </div>
        )}

        {/* Main 2-column grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Observation Feed (2/3) */}
          <div className="lg:col-span-2">
            <KairosObservationFeed minutes={60} />
          </div>

          {/* Right: Status + Watchers (1/3) */}
          <div className="space-y-4">
            {/* Status Card */}
            <Card>
              <CardHeader>
                <CardTitle>System Status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {statusLoading && !status && (
                  <div className="space-y-2 animate-pulse">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-8 rounded-lg bg-muted" />
                    ))}
                  </div>
                )}

                {status && (
                  <>
                    {/* Status rows */}
                    <div className="space-y-2 text-xs">
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Enabled</span>
                        <Badge variant={status.enabled ? "bull" : "neutral"}>
                          {status.enabled ? "Yes" : "No"}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Running</span>
                        <Badge variant={status.running ? "bull" : "warn"}>
                          {status.running ? "Yes" : "No"}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Ticks today</span>
                        <span className="font-mono font-semibold text-foreground">
                          {status.tick_count}
                        </span>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Watchers</span>
                        <span className="font-mono font-semibold text-foreground">
                          {status.watcher_count}
                        </span>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Uptime</span>
                        <span className="font-mono font-semibold text-foreground">
                          {formatUptime(status.uptime_seconds)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          Errors
                        </span>
                        <Badge variant={status.error_count > 0 ? "warn" : "neutral"}>
                          {status.error_count}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          Last tick
                        </span>
                        <span className="text-muted-foreground text-[11px]">
                          {timeAgo(status.last_tick)}
                        </span>
                      </div>
                    </div>

                    {/* Manual tick button */}
                    <button
                      onClick={handleManualTick}
                      disabled={tickLoading || !status.enabled}
                      className="w-full flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs font-medium text-foreground hover:bg-muted/60 hover:border-accent/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {tickLoading ? (
                        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Zap className="h-3.5 w-3.5 text-accent" />
                      )}
                      {tickLoading ? "Triggering…" : "Manual Tick"}
                    </button>

                    {tickResult && (
                      <p
                        className={`text-[11px] text-center ${
                          tickResult.startsWith("Failed")
                            ? "text-bear"
                            : "text-bull"
                        }`}
                      >
                        {tickResult}
                      </p>
                    )}

                    {/* Dream link */}
                    <a
                      href={`/kairos?dream=${yesterday}`}
                      className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-accent transition-colors"
                    >
                      <ChevronRight className="h-3 w-3" />
                      View yesterday&apos;s dream summary
                    </a>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Watcher Cards */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
                Watchers
              </p>

              {watchersLoading && watchers.length === 0 && (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-16 rounded-xl border border-border bg-card animate-pulse"
                    />
                  ))}
                </div>
              )}

              {watchersError && (
                <div className="rounded-xl border border-bear/20 bg-bear/5 p-3 text-center">
                  <p className="text-xs text-bear">Failed to load watchers</p>
                </div>
              )}

              {!watchersLoading && !watchersError && watchers.length === 0 && (
                <div className="rounded-xl border border-border bg-muted/20 p-4 text-center">
                  <p className="text-xs text-muted-foreground">No watchers registered</p>
                </div>
              )}

              {watchers.map((w) => (
                <WatcherCard key={w.name} watcher={w} />
              ))}
            </div>
          </div>
        </div>

        {/* Dream Summary Section */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <p className="text-sm font-bold text-foreground">Dream Summaries</p>
            <span className="text-xs text-muted-foreground">— LLM-synthesized observation digests</span>
          </div>

          <DreamAccordion
            label="Yesterday's Dream"
            dream={yesterdayDream}
            defaultOpen
          />
          <DreamAccordion
            label="Today So Far"
            dream={todayDream}
            defaultOpen={false}
          />
        </div>

        <p className="text-xs text-muted-foreground text-center pb-2">
          Observations auto-refresh every 15s. Status and watchers auto-refresh every 30s.
        </p>
      </main>
    </div>
  );
}
