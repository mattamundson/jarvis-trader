"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Loader2,
  Terminal,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface IBConnectionTestResult {
  connected: boolean;
  port: number;
  mode: string;
  latency_ms: number | null;
  account_id: string | null;
  error: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Mask an account ID: show first 2 + last 2 characters, e.g. "U***23" */
function maskAccountId(id: string): string {
  if (id.length <= 4) return id;
  const first = id.slice(0, 2);
  const last = id.slice(-2);
  const stars = "*".repeat(Math.max(3, id.length - 4));
  return `${first}${stars}${last}`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={`text-xs font-medium text-foreground ${mono ? "font-mono" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function IbGatewayDetailCard() {
  const [data, setData] = useState<IBConnectionTestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [engineDown, setEngineDown] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  async function fetchStatus() {
    try {
      const payload = await fetchEngine<IBConnectionTestResult>(`/ib/connection-test`);
      setData(payload);
      setEngineDown(false);
      setLastChecked(new Date());
    } catch {
      setEngineDown(true);
      setData(null);
      setLastChecked(new Date());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 30_000);
    return () => clearInterval(id);
  }, []);

  // ── Status badge variant ───────────────────────────────────────────────────

  const badgeVariant: "bull" | "bear" | "warn" =
    loading
      ? "warn"
      : engineDown || !data
      ? "bear"
      : data.connected
      ? "bull"
      : "bear";

  const badgeLabel = loading
    ? "Testing..."
    : engineDown || !data
    ? "Engine Down"
    : data.connected
    ? "Connected"
    : "Disconnected";

  // ── Gateway mode label ─────────────────────────────────────────────────────

  const port = data?.port ?? null;
  const isPaper = port === 4002 || data?.mode?.toLowerCase().includes("paper");
  const gatewayMode = data
    ? isPaper
      ? "Paper"
      : "Live"
    : null;

  // ── Connection icon ────────────────────────────────────────────────────────

  const ConnectionIcon =
    loading ? Loader2 : data?.connected ? Wifi : WifiOff;

  const iconColorClass =
    loading
      ? "text-muted-foreground animate-spin"
      : data?.connected
      ? "text-bull"
      : "text-bear";

  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ConnectionIcon className={`h-4 w-4 shrink-0 ${iconColorClass}`} />
            <CardTitle className="text-sm font-semibold text-foreground">
              IB Gateway Details
            </CardTitle>
          </div>
          <Badge variant={badgeVariant}>{badgeLabel}</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Engine unreachable */}
        {engineDown && !loading && (
          <div className="flex items-start gap-2 rounded-lg border border-bear/30 bg-bear/5 p-3">
            <AlertCircle className="h-4 w-4 text-bear shrink-0 mt-0.5" />
            <p className="text-xs text-bear">
              Engine unreachable — verify the engine is running and reachable through the dashboard proxy.
            </p>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2 animate-pulse">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="flex items-center justify-between py-1.5 border-b border-border/50"
              >
                <div className="h-3 w-24 rounded bg-muted" />
                <div className="h-3 w-20 rounded bg-muted" />
              </div>
            ))}
          </div>
        )}

        {/* Details grid */}
        {!loading && data && (
          <div className="space-y-0">
            {/* Gateway mode */}
            <DetailRow
              label="Gateway mode"
              value={
                gatewayMode !== null ? (
                  <Badge variant={isPaper ? "info" : "warn"}>
                    {gatewayMode} (port {port ?? "—"})
                  </Badge>
                ) : (
                  "—"
                )
              }
            />

            {/* Account */}
            <DetailRow
              label="Account"
              value={
                data.account_id ? (
                  <span className="font-mono text-xs">
                    {maskAccountId(data.account_id)}
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )
              }
            />

            {/* Host:Port */}
            <DetailRow
              label="Host : Port"
              value={
                port !== null ? (
                  <span className="font-mono text-xs">127.0.0.1:{port}</span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )
              }
              mono
            />

            {/* Paper trading */}
            <DetailRow
              label="Paper trading"
              value={
                <Badge variant={isPaper ? "info" : "warn"}>
                  {isPaper ? "Yes" : "No"}
                </Badge>
              }
            />

            {/* Latency */}
            <DetailRow
              label="Latency"
              value={
                data.latency_ms !== null ? (
                  <span
                    className={`flex items-center gap-1 font-mono text-xs ${
                      data.latency_ms < 50
                        ? "text-bull"
                        : data.latency_ms < 200
                        ? "text-warn"
                        : "text-bear"
                    }`}
                  >
                    <Zap className="h-3 w-3" />
                    {data.latency_ms.toFixed(1)} ms
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )
              }
            />

            {/* Market data (derived from connection status) */}
            <DetailRow
              label="Market data"
              value={
                <Badge variant={data.connected ? "bull" : "bear"}>
                  {data.connected ? "Connected" : "Disconnected"}
                </Badge>
              }
            />
          </div>
        )}

        {/* Error message from IB */}
        {!loading && data?.error && (
          <div className="rounded-lg border border-bear/30 bg-bear/5 px-3 py-2">
            <p className="text-xs text-bear font-mono break-all">{data.error}</p>
          </div>
        )}

        {/* Disconnected — startup instructions */}
        {!loading && data && !data.connected && (
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-1.5">
            <div className="flex items-center gap-1.5">
              <Terminal className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <p className="text-xs font-semibold text-foreground">
                How to start IB Gateway
              </p>
            </div>
            <ol className="list-decimal list-inside space-y-0.5 pl-0.5">
              <li className="text-[11px] text-muted-foreground">
                Launch IB Gateway (not TWS) from IBKR desktop app
              </li>
              <li className="text-[11px] text-muted-foreground">
                Log in and select <span className="font-semibold">Paper Trading</span>
              </li>
              <li className="text-[11px] text-muted-foreground">
                Confirm socket port is <span className="font-mono font-semibold">4002</span>
              </li>
              <li className="text-[11px] text-muted-foreground">
                Enable <span className="font-semibold">API connections</span> in Configure → Settings
              </li>
            </ol>
          </div>
        )}

        {/* Port reference note */}
        <p className="text-[11px] text-muted-foreground/60 text-right">
          Paper mode: port 4002 | Live mode: port 4001
        </p>

        {/* Last checked */}
        {lastChecked && (
          <div className="flex items-center justify-end">
            <StalenessIndicator lastUpdated={lastChecked} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
