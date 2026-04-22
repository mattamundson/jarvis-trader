"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Activity, RefreshCw, Target, ShieldAlert, TrendingUp } from "lucide-react";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────

interface MGCSignalData {
  signal?: string;
  direction?: string | null;
  atr?: number | null;
  regime?: string;
  stc_val?: number;
  [key: string]: unknown;
}

interface ATRMetrics {
  atr: number;
  stopDistancePts: number;
  stopDistanceDollar: number;
  targetDistancePts: number;
  targetDistanceDollar: number;
  rr: number;
  maxContracts: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const MES_MULTIPLIER = 5; // $5 per point
const ACCOUNT_SIZE = 10_000; // $10k example account
const RISK_PER_TRADE = 100; // $100 risk per trade (1% of $10k)

function computeMetrics(atr: number): ATRMetrics {
  const stopDistancePts = atr * 0.70;
  const stopDistanceDollar = stopDistancePts * MES_MULTIPLIER;
  const targetDistancePts = atr * 1.50;
  const targetDistanceDollar = targetDistancePts * MES_MULTIPLIER;
  const rr = 1.50 / 0.70;
  const maxContracts = Math.max(1, Math.floor(RISK_PER_TRADE / stopDistanceDollar));
  return {
    atr,
    stopDistancePts,
    stopDistanceDollar,
    targetDistancePts,
    targetDistanceDollar,
    rr,
    maxContracts,
  };
}

type VolatilityLevel = "Low Volatility" | "Normal Range" | "High Volatility" | "Extreme";
type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function getVolatilityLevel(atr: number): { label: VolatilityLevel; variant: BadgeVariant } {
  if (atr < 1.5) return { label: "Low Volatility", variant: "info" };
  if (atr < 3.0) return { label: "Normal Range", variant: "bull" };
  if (atr < 5.0) return { label: "High Volatility", variant: "warn" };
  return { label: "Extreme", variant: "bear" };
}

function fmtNum(n: number, decimals = 2): string {
  return n.toFixed(decimals);
}

function fmtDollar(n: number): string {
  return `$${n.toFixed(2)}`;
}

// ── Component ──────────────────────────────────────────────────────────────

export function VolatilityWidget() {
  const [metrics, setMetrics] = useState<ATRMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchEngine(`/paper/mgc-signal`);
      if (json.atr == null || typeof json.atr !== "number") {
        throw new Error("ATR data unavailable");
      }
      setMetrics(computeMetrics(json.atr));
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
      setMetrics(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const vol = metrics ? getVolatilityLevel(metrics.atr) : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base font-semibold tracking-tight">
              ATR Volatility
            </CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {vol && (
              <Badge variant={vol.variant}>{vol.label}</Badge>
            )}
            {!vol && !error && !loading && (
              <Badge variant="neutral">No Data</Badge>
            )}
            <button
              type="button"
              onClick={fetchData}
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
              aria-label="Refresh ATR volatility"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastUpdated && (
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Updated{" "}
            {lastUpdated.toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
              hour12: false,
            })}
            &nbsp;&bull;&nbsp;auto-refresh 30s &nbsp;&bull;&nbsp;/paper/mgc-signal
          </p>
        )}
      </CardHeader>

      <CardContent>
        {/* Loading skeleton */}
        {!metrics && !error && loading && (
          <p className="text-xs text-muted-foreground py-4 text-center">
            Loading ATR data&hellip;
          </p>
        )}

        {/* Error / unavailable */}
        {error && (
          <div className="flex flex-col items-center gap-2 py-4">
            <ShieldAlert className="h-6 w-6 text-bear/70" />
            <p className="text-xs text-bear text-center">
              {error === "ATR data unavailable"
                ? "ATR data unavailable — engine may still be computing indicators."
                : `Error: ${error}`}
            </p>
            <button
              type="button"
              onClick={fetchData}
              className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* Metrics */}
        {metrics && (
          <>
            {/* ATR value hero */}
            <div className="flex items-center gap-3 mb-4">
              <span className="text-3xl font-mono font-bold tabular-nums text-foreground">
                {fmtNum(metrics.atr)} pts
              </span>
              <span className="text-xs text-muted-foreground">Current ATR (MGC/MES)</span>
            </div>

            {/* Metrics grid */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-3">
              {/* Stop Distance */}
              <div className="rounded-lg border border-border bg-muted/30 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground uppercase tracking-wide font-medium">
                  <ShieldAlert className="h-3 w-3" />
                  Stop Distance
                </div>
                <span className="font-mono text-sm font-semibold text-foreground tabular-nums">
                  {fmtNum(metrics.stopDistancePts)} pts
                </span>
                <span className="font-mono text-xs text-bear tabular-nums">
                  {fmtDollar(metrics.stopDistanceDollar)} / contract
                </span>
              </div>

              {/* Target Distance */}
              <div className="rounded-lg border border-border bg-muted/30 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground uppercase tracking-wide font-medium">
                  <Target className="h-3 w-3" />
                  Target Distance
                </div>
                <span className="font-mono text-sm font-semibold text-foreground tabular-nums">
                  {fmtNum(metrics.targetDistancePts)} pts
                </span>
                <span className="font-mono text-xs text-bull tabular-nums">
                  {fmtDollar(metrics.targetDistanceDollar)} / contract
                </span>
              </div>

              {/* R:R */}
              <div className="rounded-lg border border-border bg-muted/30 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground uppercase tracking-wide font-medium">
                  <TrendingUp className="h-3 w-3" />
                  Theoretical R:R
                </div>
                <span className="font-mono text-sm font-semibold text-bull tabular-nums">
                  {fmtNum(metrics.rr, 2)}:1
                </span>
                <span className="text-[11px] text-muted-foreground">1.50 / 0.70 ATR</span>
              </div>

              {/* Max Contracts */}
              <div className="rounded-lg border border-border bg-muted/30 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground uppercase tracking-wide font-medium">
                  <Activity className="h-3 w-3" />
                  Max Contracts
                </div>
                <span className="font-mono text-sm font-semibold text-foreground tabular-nums">
                  {metrics.maxContracts}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  ${RISK_PER_TRADE} risk / $10k acct
                </span>
              </div>
            </div>

            {/* Calculation note */}
            <p className="text-[11px] text-muted-foreground">
              Based on ATR &times; 0.70 stop / ATR &times; 1.50 target &nbsp;&bull;&nbsp;
              MES multiplier ${MES_MULTIPLIER}/pt &nbsp;&bull;&nbsp;
              Stop: {fmtDollar(metrics.stopDistanceDollar)} &nbsp;&bull;&nbsp;
              Target: {fmtDollar(metrics.targetDistanceDollar)}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
