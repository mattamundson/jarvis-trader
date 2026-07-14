"use client";

import { useState } from "react";
import useSWR from "swr";
import { Search, Play, RefreshCw, CheckCircle, XCircle, Clock, Filter } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, postEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface StrategyMeta {
  name: string;
  version?: string;
  keep?: boolean;
  sharpe?: number;
  profit_factor?: number;
  win_rate?: number;
  status?: string;
  description?: string;
  symbol?: string;
  interval?: string;
  verdict?: string;
}

interface StrategiesResponse {
  total: number;
  strategies: StrategyMeta[];
}

interface DiscoveryRunResult {
  status: string;
  strategy_file?: string;
  eligible?: boolean;
  verdict?: string;
  metrics?: {
    sharpe?: number;
    calmar?: number;
    pf?: number;
    num_trades?: number;
    win_rate?: number;
    max_drawdown_pct?: number;
  };
  thoughts?: string;
  detail?: string;
}

type FilterStatus = "ALL" | "ELIGIBLE" | "DISCARD" | "NOT_VALIDATED";

// ── Helpers ───────────────────────────────────────────────────────────────

function fetcher<T = unknown>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function verdictBadge(
  strategy: StrategyMeta
): "bull" | "bear" | "warn" | "info" | "neutral" {
  const v = (strategy.verdict ?? strategy.status ?? "").toUpperCase();
  if (v === "ELIGIBLE") return "bull";
  if (v === "DISCARD") return "bear";
  if (strategy.keep) return "bull";
  if (v === "NOT_VALIDATED" || v === "") return "neutral";
  return "warn";
}

function verdictLabel(strategy: StrategyMeta): string {
  const v = strategy.verdict ?? strategy.status ?? "";
  if (v) return v.toUpperCase();
  if (strategy.keep === true) return "ELIGIBLE";
  if (strategy.keep === false) return "DISCARD";
  return "NOT_VALIDATED";
}

function metricColor(value: number | undefined, good: number, warn: number): string {
  if (value === undefined || value === null) return "text-zinc-500";
  if (value >= good) return "text-bull";
  if (value >= warn) return "text-warn";
  return "text-bear";
}

function formatMetric(value: number | undefined, decimals = 2): string {
  if (value === undefined || value === null) return "—";
  return value.toFixed(decimals);
}

// ── Component ─────────────────────────────────────────────────────────────

export function StrategyDiscoveryBrowser() {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>("ALL");
  const [runSymbol, setRunSymbol] = useState<"MCL" | "MNQ">("MCL");
  const [isRunning, setIsRunning] = useState(false);
  const [lastRunResult, setLastRunResult] = useState<DiscoveryRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const { data, error, mutate, isValidating } = useSWR<StrategiesResponse>(
    "/discovery/strategies",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  const loading = !data && !error;

  // Filter strategies
  const strategies = (data?.strategies ?? []).filter((s) => {
    if (filterStatus === "ALL") return true;
    const label = verdictLabel(s);
    return label === filterStatus;
  });

  // Run discovery cycle
  const handleRunCycle = async () => {
    if (isRunning) return;
    setIsRunning(true);
    setRunError(null);
    setLastRunResult(null);
    try {
      const res = await postEngine<DiscoveryRunResult>(
        `/discovery/run-cycle?symbol=${runSymbol}`
      );
      setLastRunResult(res);
      mutate(); // refresh strategy list
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Discovery cycle failed");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-cyan-400" />
          <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-cyan-400">
            Strategy Discovery Browser
          </span>
        </div>

        {data && (
          <span className="font-mono text-[10px] text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded">
            {data.total} strategies loaded
          </span>
        )}

        {/* Filter chips */}
        <div className="flex items-center gap-1 ml-auto flex-wrap">
          <Filter className="h-3 w-3 text-zinc-600 mr-0.5" />
          {(["ALL", "ELIGIBLE", "DISCARD", "NOT_VALIDATED"] as FilterStatus[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilterStatus(f)}
              className={`font-mono text-[9px] uppercase tracking-wider px-2 py-0.5 rounded border transition-colors ${
                filterStatus === f
                  ? "border-cyan-500 bg-cyan-500/10 text-cyan-400"
                  : "border-zinc-700 bg-zinc-900 text-zinc-500 hover:border-zinc-600 hover:text-zinc-400"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="h-px bg-zinc-800" />

      {/* Run Discovery Cycle control */}
      <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <Play className="h-3.5 w-3.5 text-zinc-500" />
        <span className="font-mono text-[10px] text-zinc-400 uppercase tracking-wider">Run Discovery Cycle</span>
        <select
          value={runSymbol}
          onChange={(e) => setRunSymbol(e.target.value as "MCL" | "MNQ")}
          className="font-mono text-[10px] bg-zinc-800 border border-zinc-700 text-zinc-300 rounded px-2 py-1 focus:outline-none focus:border-cyan-600"
        >
          <option value="MCL">MCL</option>
          <option value="MNQ">MNQ</option>
        </select>
        <button
          onClick={handleRunCycle}
          disabled={isRunning}
          className="flex items-center gap-1.5 rounded border border-cyan-600/40 bg-cyan-600/10 px-3 py-1 font-mono text-[10px] text-cyan-400 hover:bg-cyan-600/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? (
            <>
              <RefreshCw className="h-3 w-3 animate-spin" />
              Running…
            </>
          ) : (
            <>
              <Play className="h-3 w-3" />
              Generate + Evaluate
            </>
          )}
        </button>
        <button
          onClick={() => mutate()}
          disabled={isValidating}
          className="ml-auto flex items-center gap-1 font-mono text-[10px] text-zinc-500 hover:text-zinc-400 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`h-3 w-3 ${isValidating ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Run result feedback */}
      {lastRunResult && (
        <div className={`rounded-lg border p-3 space-y-1 ${
          lastRunResult.eligible ? "border-bull/30 bg-bull/5" : "border-bear/20 bg-bear/5"
        }`}>
          <div className="flex items-center gap-2">
            {lastRunResult.eligible
              ? <CheckCircle className="h-3.5 w-3.5 text-bull" />
              : <XCircle className="h-3.5 w-3.5 text-bear" />
            }
            <span className={`font-mono text-[10px] font-bold uppercase ${
              lastRunResult.eligible ? "text-bull" : "text-bear"
            }`}>
              {lastRunResult.verdict ?? (lastRunResult.eligible ? "ELIGIBLE" : "DISCARD")}
            </span>
            {lastRunResult.strategy_file && (
              <span className="font-mono text-[9px] text-zinc-500 truncate ml-auto">
                {lastRunResult.strategy_file.split("/").pop()}
              </span>
            )}
          </div>
          {lastRunResult.metrics && (
            <div className="grid grid-cols-3 gap-2 mt-2">
              <MetricPill label="Sharpe" value={formatMetric(lastRunResult.metrics.sharpe)} colorClass={metricColor(lastRunResult.metrics.sharpe, 1.5, 0.8)} />
              <MetricPill label="PF" value={formatMetric(lastRunResult.metrics.pf)} colorClass={metricColor(lastRunResult.metrics.pf, 2.0, 1.3)} />
              <MetricPill label="WR" value={lastRunResult.metrics.win_rate !== undefined ? `${(lastRunResult.metrics.win_rate * 100).toFixed(1)}%` : "—"} colorClass={metricColor(lastRunResult.metrics.win_rate, 0.55, 0.45)} />
            </div>
          )}
          {lastRunResult.thoughts && (
            <p className="font-mono text-[10px] text-zinc-400 leading-snug mt-1 line-clamp-2">
              {lastRunResult.thoughts}
            </p>
          )}
        </div>
      )}

      {runError && (
        <div className="rounded-lg border border-bear/30 bg-bear/5 p-3">
          <p className="font-mono text-[10px] text-bear">{runError}</p>
        </div>
      )}

      {/* Strategy table */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-zinc-800/40" />
          ))}
        </div>
      )}

      {error && (
        <p className="font-mono text-xs text-muted-foreground">Engine offline — discovery unavailable.</p>
      )}

      {!loading && !error && (
        <>
          {/* Table header */}
          <div className="rounded-lg border border-zinc-800 overflow-hidden">
            <div className="grid grid-cols-12 gap-2 px-3 py-2 border-b border-zinc-800 bg-zinc-900">
              <span className="col-span-4 font-mono text-[9px] uppercase tracking-widest text-zinc-500">Strategy</span>
              <span className="col-span-1 font-mono text-[9px] uppercase tracking-widest text-zinc-500 text-center">Keep</span>
              <span className="col-span-2 font-mono text-[9px] uppercase tracking-widest text-zinc-500 text-right">Sharpe</span>
              <span className="col-span-2 font-mono text-[9px] uppercase tracking-widest text-zinc-500 text-right">Prof. Factor</span>
              <span className="col-span-1 font-mono text-[9px] uppercase tracking-widest text-zinc-500 text-right">WR</span>
              <span className="col-span-2 font-mono text-[9px] uppercase tracking-widest text-zinc-500 text-right">Status</span>
            </div>

            {/* Table rows */}
            <div className="divide-y divide-zinc-800/60">
              {strategies.length === 0 && (
                <div className="flex items-center justify-center py-8 gap-2 text-zinc-600">
                  <Clock className="h-4 w-4" />
                  <span className="font-mono text-xs">
                    {filterStatus !== "ALL" ? `No ${filterStatus} strategies` : "No strategies loaded"}
                  </span>
                </div>
              )}

              {strategies.map((s, idx) => (
                <div
                  key={`${s.name}-${idx}`}
                  className="grid grid-cols-12 gap-2 px-3 py-2.5 hover:bg-zinc-800/30 transition-colors items-center"
                >
                  {/* Name */}
                  <div className="col-span-4 min-w-0">
                    <p className="font-mono text-[11px] text-zinc-200 truncate font-medium">{s.name}</p>
                    {(s.symbol || s.interval) && (
                      <p className="font-mono text-[9px] text-zinc-600">
                        {s.symbol} {s.interval}
                        {s.version && ` · v${s.version}`}
                      </p>
                    )}
                  </div>

                  {/* Keep bool */}
                  <div className="col-span-1 flex justify-center">
                    {s.keep === true
                      ? <CheckCircle className="h-3.5 w-3.5 text-bull" />
                      : s.keep === false
                      ? <XCircle className="h-3.5 w-3.5 text-bear" />
                      : <span className="font-mono text-[10px] text-zinc-600">—</span>
                    }
                  </div>

                  {/* Sharpe */}
                  <span className={`col-span-2 font-mono text-xs tabular-nums text-right ${metricColor(s.sharpe, 1.5, 0.8)}`}>
                    {formatMetric(s.sharpe)}
                  </span>

                  {/* Profit Factor */}
                  <span className={`col-span-2 font-mono text-xs tabular-nums text-right ${metricColor(s.profit_factor, 2.0, 1.3)}`}>
                    {formatMetric(s.profit_factor)}
                  </span>

                  {/* Win Rate */}
                  <span className={`col-span-1 font-mono text-xs tabular-nums text-right ${metricColor(s.win_rate, 0.55, 0.45)}`}>
                    {s.win_rate !== undefined ? `${(s.win_rate * 100).toFixed(0)}%` : "—"}
                  </span>

                  {/* Status badge */}
                  <div className="col-span-2 flex justify-end">
                    <Badge variant={verdictBadge(s)}>
                      {verdictLabel(s)}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <p className="font-mono text-[9px] text-zinc-700 text-right">
            {filterStatus !== "ALL" ? `${strategies.length} of ${data?.total ?? 0} shown` : `${data?.total ?? 0} strategies`} · 30s poll
          </p>
        </>
      )}
    </div>
  );
}

// ── Helper sub-components ─────────────────────────────────────────────────

function MetricPill({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string;
  colorClass: string;
}) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-center">
      <p className="font-mono text-[9px] text-zinc-600 uppercase mb-0.5">{label}</p>
      <p className={`font-mono text-xs font-bold tabular-nums ${colorClass}`}>{value}</p>
    </div>
  );
}
