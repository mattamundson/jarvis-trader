"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, fetchEngineRaw } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────

// Shape returned by POST /notifications/vix-alert-check
interface VixAlertResponse {
  vix: number;
  regime: string;
  sent?: boolean;
  reason?: string;
  alert_level?: string;
  guidance?: string;
}

// Shape returned by GET /settings/risk (for max_contracts)
interface RiskSettingsResponse {
  config: {
    max_contracts: number;
    [key: string]: number;
  };
  circuit_breakers: Record<string, unknown>;
}

interface VIXData {
  vix_value: number;
  regime: string;
  max_contracts: number;
  filter_active: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function regimeToBadge(regime: string): BadgeVariant {
  switch (regime.toUpperCase()) {
    case "CALM":
    case "NORMAL":
      return "bull";
    case "CAUTION":
      return "warn";
    case "ELEVATED":
      return "bear";
    case "EXTREME":
      return "bear";
    default:
      return "info";
  }
}

function regimeLabel(regime: string): string {
  switch (regime.toUpperCase()) {
    case "CALM":   return "CALM";
    case "NORMAL": return "NORMAL";
    case "CAUTION":  return "CAUTION";
    case "ELEVATED": return "ELEVATED";
    case "EXTREME":  return "EXTREME";
    default: return regime.toUpperCase();
  }
}

// EXTREME regime means filter is blocking trades; ELEVATED reduces size.
// We treat the filter as "active" (i.e. impacting trades) when regime is not CALM/NORMAL.
function isFilterActive(regime: string): boolean {
  return !["CALM", "NORMAL"].includes(regime.toUpperCase());
}

// ── Component ─────────────────────────────────────────────────────────────

export function VIXRegimeCard() {
  const [data, setData] = useState<VIXData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchData = async () => {
    try {
      // POST via Next rewrite → engine (not browser origin)
      const vixRes = await fetchEngineRaw("/notifications/vix-alert-check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });

      if (vixRes.status === 404) {
        setNotFound(true);
        return;
      }

      if (!vixRes.ok) {
        throw new Error(`VIX endpoint returned ${vixRes.status}`);
      }

      const vixJson: VixAlertResponse = await vixRes.json();

      // GET /settings/risk — fetchEngine returns parsed JSON (not Response)
      let maxContracts = 1;
      try {
        const riskJson = await fetchEngine<RiskSettingsResponse>("/settings/risk");
        maxContracts = riskJson.config?.max_contracts ?? 1;
      } catch {
        // non-fatal — leave maxContracts as 1
      }

      const regime = vixJson.regime ?? "UNKNOWN";

      setData({
        vix_value: vixJson.vix,
        regime,
        max_contracts: maxContracts,
        filter_active: isFilterActive(regime),
      });
      setLastUpdated(new Date());
      setNotFound(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    }
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 300_000); // refresh every 5 minutes
    return () => clearInterval(id);
  }, []);

  // ── Render: endpoint not found ──────────────────────────────────────────
  if (notFound) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">VIX Regime Filter</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Badge variant="info">INFO</Badge>
            <span className="text-sm text-muted-foreground">
              VIX monitoring configured — engine running
            </span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Render: error state ─────────────────────────────────────────────────
  if (error && !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">VIX Regime Filter</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Badge variant="warn">WARN</Badge>
            <span className="text-xs text-muted-foreground truncate">{error}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Render: loading ─────────────────────────────────────────────────────
  if (!data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">VIX Regime Filter</CardTitle>
        </CardHeader>
        <CardContent>
          <span className="text-xs text-muted-foreground animate-pulse">Loading VIX data…</span>
        </CardContent>
      </Card>
    );
  }

  // ── Render: data ────────────────────────────────────────────────────────
  const badgeVariant = regimeToBadge(data.regime);
  const label = regimeLabel(data.regime);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">VIX Regime Filter</CardTitle>
          <Badge variant={badgeVariant}>{label}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* Big VIX metric */}
          <div className="flex items-end gap-2">
            <span className="text-3xl font-bold tabular-nums">
              {data.vix_value.toFixed(2)}
            </span>
            <span className="text-xs text-muted-foreground mb-1">VIX</span>
          </div>

          {/* Secondary stats */}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="rounded bg-muted/40 px-2 py-1.5">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">
                Max Contracts
              </p>
              <p className="font-semibold tabular-nums">{data.max_contracts}</p>
            </div>

            <div className="rounded bg-muted/40 px-2 py-1.5">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">
                Filter
              </p>
              <div className="flex items-center gap-1">
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    data.filter_active ? "bg-amber-400" : "bg-emerald-400"
                  }`}
                />
                <span className="font-semibold">
                  {data.filter_active ? "Active" : "Inactive"}
                </span>
              </div>
            </div>
          </div>

          {/* Last updated */}
          {lastUpdated && (
            <p className="text-[10px] text-muted-foreground text-right">
              Updated {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
