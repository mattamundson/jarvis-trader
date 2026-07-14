"use client";
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

type AlertEntry = {
  id: number;
  alert_type: string;
  symbol?: string;
  message: string;
  channel: string;
  status: "sent" | "failed" | "suppressed";
  error?: string;
  created_at: string;
};

const STATUS_VARIANT: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  sent: "bull",
  failed: "bear",
  suppressed: "warn",
};

const TYPE_LABELS: Record<string, string> = {
  trade_opened: "Trade Open",
  trade_closed: "Trade Close",
  morning_briefing: "Morning Brief",
  vix_alert: "VIX Alert",
  circuit_breaker: "Circuit Breaker",
  notification: "Notification",
};

export function AlertHistoryLog() {
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    const load = () => {
      const path =
        filter === "all"
          ? "/alerts/history?limit=50"
          : `/alerts/history?limit=50&alert_type=${filter}`;
      fetchEngine<{ alerts: AlertEntry[] }>(path)
        .then((d) => {
          setAlerts(d.alerts ?? []);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [filter]);

  const types = [
    "all",
    "trade_opened",
    "trade_closed",
    "morning_briefing",
    "vix_alert",
    "circuit_breaker",
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Alert History</CardTitle>
          <Badge variant="neutral">{alerts.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* filter chips */}
        <div className="flex gap-1.5 flex-wrap px-4 pb-3">
          {types.map((t) => (
            <button
              key={t}
              onClick={() => setFilter(t)}
              className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                filter === t
                  ? "bg-accent text-accent-foreground border-accent"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {t === "all" ? "All" : (TYPE_LABELS[t] ?? t)}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-10 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">No alerts yet.</p>
        ) : (
          <div className="divide-y divide-border max-h-72 overflow-y-auto">
            {alerts.map((a) => (
              <div
                key={a.id}
                className="px-4 py-2 cursor-pointer hover:bg-muted/40"
                onClick={() => setExpanded(expanded === a.id ? null : a.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Badge variant={STATUS_VARIANT[a.status] ?? "neutral"}>
                      {a.status}
                    </Badge>
                    <span className="text-xs font-medium truncate">
                      {TYPE_LABELS[a.alert_type] ?? a.alert_type}
                      {a.symbol ? ` · ${a.symbol}` : ""}
                    </span>
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {new Date(a.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
                {expanded === a.id && (
                  <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-words">
                    {a.error ? `Error: ${a.error}` : a.message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
