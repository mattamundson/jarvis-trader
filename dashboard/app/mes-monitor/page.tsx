"use client";

import useSWR from "swr";
import { Activity, AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface MonitorStatusResponse {
  symbol: string;
  state: string;
  last_price: number | null;
  last_signal: string | null;
  last_confidence: number | null;
  last_update_utc: string | null;
}

interface AlertResponse {
  timestamp: string;
  symbol: string;
  direction: string | null;
  confidence: number;
  price: number;
  reason: string;
  regime: string;
}

// ── Fetcher ────────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Components ────────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="font-mono text-2xl font-bold tabular-nums leading-none">{value}</p>
      {sub && <p className="font-mono text-[10px] text-muted-foreground truncate">{sub}</p>}
    </div>
  );
}

function Badge({ ok, label }: { ok: boolean | null; label: string }) {
  const color = ok === true ? "#00ff88" : ok === false ? "#ff4444" : "#888";
  const icon = ok === true ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />;
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ color }}>{icon}</span>
      <span className="font-mono text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const REFRESH_MS = 30_000;

export default function MesMonitorPage() {
  const { data: status, error: statusError } = useSWR<MonitorStatusResponse>("/mes-monitor/status", fetcher, {
    refreshInterval: REFRESH_MS,
  });
  const { data: alerts, error: alertsError } = useSWR<AlertResponse[]>("/mes-monitor/alerts?limit=20", fetcher, {
    refreshInterval: REFRESH_MS,
  });

  const statusOk = !statusError && !!status;
  const alertsOk = !alertsError && !!alerts;

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">MES 24x7 Monitor</h1>
          <p className="text-muted-foreground text-sm">Level-based suggestion panel — no auto-execution</p>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Activity className="h-4 w-4" />
          <span className="font-mono text-xs">status: {statusOk ? "live" : "unreachable"}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard
          label="Symbol"
          value={status?.symbol ?? "—"}
          sub={status?.last_update_utc ?? "awaiting data"}
        />
        <MetricCard
          label="Last Signal"
          value={status?.last_signal ?? "—"}
          sub={status?.last_price ? `@ ${status.last_price}` : "no signal yet"}
        />
        <MetricCard
          label="Confidence"
          value={status?.last_confidence != null ? `${(status.last_confidence * 100).toFixed(0)}%` : "—"}
          sub="scaled by regime"
        />
      </div>

      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="font-mono text-xs font-bold uppercase tracking-wider text-muted-foreground">Recent Alerts</p>
          <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
        </div>
        <div className="space-y-2">
          {!alertsOk && (
            <p className="text-sm text-muted-foreground">No alert data available.</p>
          )}
          {alertsOk && alerts.length === 0 && (
            <p className="text-sm text-muted-foreground">No alerts yet.</p>
          )}
          {alertsOk &&
            alerts.map((a, idx) => (
              <div key={idx} className="rounded-lg border border-border/60 bg-background/40 p-3 flex items-center justify-between">
                <div>
                  <p className="font-mono text-sm font-semibold">{a.reason}</p>
                  <p className="font-mono text-[10px] text-muted-foreground">
                    {a.timestamp} · {a.direction ?? "none"} · {a.regime}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm">{a.price.toFixed(2)}</p>
                  <p className="font-mono text-[10px] text-muted-foreground">{(a.confidence * 100).toFixed(0)}%</p>
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
