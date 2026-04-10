"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchTVSnapshot, type TVBridgeSnapshot } from "@/lib/api";

// ── Color / badge constants (Iron Man HUD vibe) ───────────────────────────
const QUALITY_BADGE: Record<TVBridgeSnapshot["data_quality"], {
  variant: "bull" | "bear" | "warn" | "info" | "neutral";
  label: string;
}> = {
  live: { variant: "bull", label: "LIVE" },
  stale: { variant: "warn", label: "STALE" },
  unavailable: { variant: "bear", label: "OFFLINE" },
};

const REGIME_CLASS: Record<string, string> = {
  TRENDING_BULL: "text-emerald-300",
  TRENDING_BEAR: "text-rose-300",
  RANGING: "text-slate-300",
  COMPRESSION: "text-amber-300",
  VOLATILE: "text-red-400",
};

function stcClass(value: number | null): string {
  if (value == null) return "text-slate-500";
  if (value <= 15) return "text-emerald-400";
  if (value >= 83) return "text-rose-400";
  return "text-amber-300";
}

function compositeClass(value: number | null): string {
  if (value == null) return "text-slate-500";
  if (value > 0.05) return "text-emerald-400";
  if (value < -0.05) return "text-rose-400";
  return "text-slate-300";
}

function coreyClass(value: number | null): string {
  if (value == null) return "text-slate-500";
  if (value > 0.05) return "text-emerald-400";
  if (value < -0.05) return "text-rose-400";
  return "text-amber-300";
}

function fmt(
  value: number | null | undefined,
  precision = 2,
  placeholder = "—"
): string {
  if (value == null || Number.isNaN(value)) return placeholder;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

interface PillProps {
  label: string;
  value: string;
  valueClass?: string;
}

function Pill({ label, value, valueClass = "text-slate-100" }: PillProps) {
  return (
    <div className="flex flex-col rounded border border-slate-800 bg-slate-950/50 px-3 py-2">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <span className={`font-mono text-sm font-semibold ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

export interface TVBridgeWidgetProps {
  symbol: string;
  refreshIntervalMs?: number;
}

export default function TVBridgeWidget({
  symbol,
  refreshIntervalMs = 30000,
}: TVBridgeWidgetProps) {
  const { data, error, isLoading } = useSWR<TVBridgeSnapshot>(
    `/tv/snapshot?symbol=${symbol}`,
    () => fetchTVSnapshot(symbol),
    {
      refreshInterval: refreshIntervalMs,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  const unavailable =
    !data || data.data_quality === "unavailable" || error !== undefined;
  const quality = data?.data_quality ?? "unavailable";
  const badge = QUALITY_BADGE[quality];

  return (
    <Card className="border-slate-800 bg-slate-950/80">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-200">
          <span className="text-cyan-400">TV</span>
          <span>Bridge</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">{symbol}</span>
        </CardTitle>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </CardHeader>
      <CardContent>
        {isLoading && !data ? (
          <div className="text-xs text-slate-500">Loading…</div>
        ) : unavailable ? (
          <div className="flex flex-col gap-2">
            <div className="text-xs text-slate-500">
              TradingView Desktop offline — launch TV with CDP port 9222 and
              ensure the JARVIS MCP Manifest indicator is loaded.
            </div>
            <div className="font-mono text-[11px] text-slate-600">
              Last quality: {quality}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2">
            <Pill
              label="STC"
              value={fmt(data!.stc_value, 1)}
              valueClass={stcClass(data!.stc_value)}
            />
            <Pill
              label="State"
              value={data!.stc_state ?? "—"}
              valueClass={stcClass(data!.stc_value)}
            />
            <Pill
              label="Composite"
              value={fmt(data!.composite_score, 2)}
              valueClass={compositeClass(data!.composite_score)}
            />
            <Pill
              label="Regime"
              value={data!.regime ?? "—"}
              valueClass={
                REGIME_CLASS[data!.regime ?? ""] ?? "text-slate-300"
              }
            />
            <Pill label="ATR" value={fmt(data!.atr_value, 2)} />
            <Pill label="VWAP" value={fmt(data!.vwap, 2)} />
            <Pill label="IB High" value={fmt(data!.ib_high, 2)} />
            <Pill label="IB Low" value={fmt(data!.ib_low, 2)} />
            <Pill label="IB Range" value={fmt(data!.ib_range, 2)} />
            <Pill
              label="Corey"
              value={fmt(data!.corey_score, 2)}
              valueClass={coreyClass(data!.corey_score)}
            />
            <Pill label="Bias" value={data!.corey_bias ?? "—"} />
            <Pill label="Phase" value={fmt(data!.phase_oscillator, 1)} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
