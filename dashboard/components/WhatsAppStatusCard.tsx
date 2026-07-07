"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface AlertEntry {
  id: number;
  alert_type: string;
  symbol?: string;
  message: string;
  channel: string;
  status: "sent" | "failed" | "suppressed";
  error?: string;
  created_at: string;
}

interface AlertStats {
  stats: { alert_type: string; status: string; count: number }[];
  total: number;
}

interface WhatsAppState {
  configured: boolean | null; // null = unknown / loading
  toNumber?: string;         // raw WHATSAPP_TO value if reflected by engine
  lastAlert?: AlertEntry;
  totalAlerts: number;
  error: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function maskPhone(raw: string): string {
  // raw may be "whatsapp:+12125551234" or "+12125551234"
  const digits = raw.replace(/\D/g, "");
  if (digits.length >= 4) {
    return `••••${digits.slice(-4)}`;
  }
  return "••••";
}

const TYPE_LABELS: Record<string, string> = {
  trade_opened: "TRADE_SIGNAL",
  trade_closed: "TRADE_CLOSED",
  morning_briefing: "MORNING_BRIEF",
  vix_alert: "VIX_ALERT",
  circuit_breaker: "CIRCUIT_BREAKER",
  notification: "NOTIFICATION",
  test: "TEST",
};

// ── Component ─────────────────────────────────────────────────────────────

export function WhatsAppStatusCard() {
  const [state, setState] = useState<WhatsAppState>({
    configured: null,
    totalAlerts: 0,
    error: false,
  });

  const load = async () => {
    try {
      // Fetch alert history (most recent 1) and stats in parallel
      const [histData, statsData] = await Promise.all([
        fetchEngine<{ alerts: AlertEntry[]; count: number }>("/alerts/history?limit=1"),
        fetchEngine<AlertStats>("/alerts/stats"),
      ]);

      const lastAlert = histData.alerts?.[0];

      // Determine "configured": if any alert has ever been sent with status="sent"
      // we know the Twilio config was working at some point.
      const anySent = statsData.stats.some((r) => r.status === "sent");

      setState({
        configured: anySent,
        lastAlert,
        totalAlerts: statsData.total ?? 0,
        error: false,
      });
    } catch {
      // Network error or engine offline → show fallback
      setState({ configured: false, totalAlerts: 0, error: true });
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 120_000);
    return () => clearInterval(id);
  }, []);

  // ── Derived display values ───────────────────────────────────────────────

  const { configured, lastAlert, totalAlerts, error } = state;

  // NOTE: `configured` reflects whether any alert has ever been *sent* (from
  // /alerts/stats), NOT a live Twilio credential/handshake check. Label it as
  // alert flow, and never render an affirmative "configured" badge when the
  // engine is unreachable — an outage must not read as healthy.
  const connectionBadgeVariant: "bull" | "warn" | "neutral" =
    error
      ? "neutral"
      : configured === true
      ? "bull"
      : configured === false
      ? "warn"
      : "neutral";

  const connectionLabel =
    error
      ? "Engine Offline"
      : configured === true
      ? "Alerts Active"
      : configured === false
      ? "No Alerts Sent"
      : "Checking…";

  const recentType = lastAlert
    ? (TYPE_LABELS[lastAlert.alert_type] ?? lastAlert.alert_type.toUpperCase())
    : null;

  const recentStatus = lastAlert?.status ?? null;

  const toNumber = lastAlert?.message
    ? undefined // message body doesn't expose the number; skip extraction
    : undefined;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>WhatsApp Alerts</CardTitle>
          <Badge variant={connectionBadgeVariant}>{connectionLabel}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-0">
          {/* Total alerts */}
          <Row label="Total alerts sent" value={totalAlerts.toString()} />

          {/* Phone (masked) — only shown if available */}
          {toNumber && (
            <Row label="Recipient" value={maskPhone(toNumber)} mono />
          )}

          {/* Last alert sent */}
          {lastAlert ? (
            <Row
              label="Last alert"
              value={timeAgo(lastAlert.created_at)}
            />
          ) : (
            <Row label="Last alert" value="No alerts yet" />
          )}

          {/* Recent alert type */}
          {recentType && (
            <Row label="Recent type" value={recentType} mono />
          )}

          {/* Recent alert status */}
          {recentStatus && (
            <div className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
              <span className="text-xs text-muted-foreground">Last status</span>
              <Badge
                variant={
                  recentStatus === "sent"
                    ? "bull"
                    : recentStatus === "failed"
                    ? "bear"
                    : "warn"
                }
              >
                {recentStatus}
              </Badge>
            </div>
          )}

          {/* Fallback note when engine is unreachable */}
          {error && (
            <p className="pt-2 text-[11px] text-muted-foreground">
              Engine offline — WhatsApp alert status unavailable.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Row helper ────────────────────────────────────────────────────────────

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={`text-xs font-semibold text-foreground ${mono ? "font-mono" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}
