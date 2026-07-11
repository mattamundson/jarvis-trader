"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface MGCSignalData {
  date: string;
  symbol: string;
  signal: string;         // ENTRY_NOW | WAIT_FOR_PULLBACK | FADE_EXTREME | NO_ENTRY
  direction: string | null; // LONG | SHORT | null
  regime: string;           // e.g. TRENDING_BULL, RANGING, etc.
  adaptive_stc_os: number;  // STC oversold threshold
  adaptive_stc_ob: number;  // STC overbought threshold
  entry_price: number;      // last close
  stop_level: number;       // pre-computed stop
  target_1: number;         // pre-computed target 1
  target_2: number;         // pre-computed target 2
  atr: number;              // current ATR
  bias: string;             // STRONG_BULL | LEAN_BULL | STRONG_BEAR | LEAN_BEAR | NEUTRAL
  stc_val: number;          // STC oscillator value 0–100
  stc_signal: string;       // e.g. "bullish" | "bearish" | "neutral"
  ema_trend: string;        // e.g. "bullish" | "bearish" | "neutral"
  config: string;           // human-readable config summary
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function signalBadgeVariant(signal: string, direction: string | null): "bull" | "bear" | "warn" | "neutral" {
  const s = signal.toUpperCase();
  const d = (direction ?? "").toUpperCase();

  if (s === "ENTRY_NOW") {
    if (d === "LONG") return "bull";
    if (d === "SHORT") return "bear";
    return "bull";
  }
  if (s === "FADE_EXTREME") return "warn";
  if (s === "WAIT_FOR_PULLBACK") return "warn";
  return "neutral";
}

function signalLabel(signal: string, direction: string | null): string {
  const s = signal.toUpperCase();
  const d = (direction ?? "").toUpperCase();

  if (s === "ENTRY_NOW") return d ? `ENTRY NOW — ${d}` : "ENTRY NOW";
  if (s === "WAIT_FOR_PULLBACK") return "WAIT — PULLBACK";
  if (s === "FADE_EXTREME") return "FADE EXTREME";
  if (s === "NO_ENTRY") return "NO ENTRY";
  return signal.toUpperCase();
}

function biasBadgeVariant(bias: string): "bull" | "bear" | "warn" | "neutral" {
  const b = bias.toUpperCase();
  if (b === "STRONG_BULL" || b === "LEAN_BULL") return "bull";
  if (b === "STRONG_BEAR" || b === "LEAN_BEAR") return "bear";
  if (b === "NEUTRAL") return "warn";
  return "neutral";
}

function stcTextClass(val: number): string {
  if (val >= 80) return "text-[#ff4444]";
  if (val >= 60) return "text-[#ffcc00]";
  if (val <= 20) return "text-[#00ff88]";
  if (val <= 40) return "text-[#00d4ff]";
  return "text-[#e0e0e0]";
}

function stcBgClass(val: number): string {
  if (val >= 80) return "bg-[#ff4444]";
  if (val >= 60) return "bg-[#ffcc00]";
  if (val <= 20) return "bg-[#00ff88]";
  if (val <= 40) return "bg-[#00d4ff]";
  return "bg-[#e0e0e0]";
}

function heroBgClass(variant: "bull" | "bear" | "warn" | "neutral"): string {
  if (variant === "bull") return "bg-[#00ff8808]";
  if (variant === "bear") return "bg-[#ff444408]";
  return "bg-[#ffcc0008]";
}

function heroBorderClass(variant: "bull" | "bear" | "warn" | "neutral"): string {
  if (variant === "bull") return "border-[#00ff8825]";
  if (variant === "bear") return "border-[#ff444425]";
  return "border-[#ffcc0025]";
}

function heroTextClass(variant: "bull" | "bear" | "warn" | "neutral"): string {
  if (variant === "bull") return "text-[#00ff88]";
  if (variant === "bear") return "text-[#ff4444]";
  return "text-[#ffcc00]";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatRow({
  label,
  value,
  sub,
  valueClassName,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#111]">
      <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">
        {label}
      </span>
      <div className="text-right">
        <span
          className={`font-mono text-sm font-bold tabular-nums ${valueClassName ?? "text-[#e0e0e0]"}`}
        >
          {value}
        </span>
        {sub && (
          <span className="font-mono text-[10px] ml-2 tabular-nums text-[#444]">
            {sub}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function SignalQueueWidget() {
  const [data, setData] = useState<MGCSignalData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<string | null>(null);

  const fetchSignal = async () => {
    try {
      const json = await fetchEngine(`/paper/mgc-signal`);
      setData(json);
      setError(null);
      setLastFetch(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch signal");
    }
  };

  useEffect(() => {
    fetchSignal();
    const timer = setInterval(fetchSignal, 30_000);
    return () => clearInterval(timer);
  }, []);

  // Derived: ATR-based stop/target when stop_level / target_1 are zero
  const entry = data?.entry_price ?? 0;
  const atr = data?.atr ?? 0;
  const computedStop =
    data && (data.stop_level === 0 || data.stop_level == null)
      ? data.direction === "SHORT"
        ? entry + atr * 0.7
        : entry - atr * 0.7
      : data?.stop_level ?? 0;
  const computedTarget1 =
    data && (data.target_1 === 0 || data.target_1 == null)
      ? data.direction === "SHORT"
        ? entry - atr * 1.5
        : entry + atr * 1.5
      : data?.target_1 ?? 0;

  const signalVariant = data
    ? signalBadgeVariant(data.signal, data.direction)
    : "neutral";
  const signalText = data
    ? signalLabel(data.signal, data.direction)
    : "—";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-mono font-bold tracking-[0.15em] uppercase">
              Current Signal State
            </CardTitle>
            <p className="font-mono text-[10px] mt-0.5 text-[#555]">
              MGC / GC=F · Daily Regime + Entry Pipeline
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={signalVariant}>{signalText}</Badge>
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]">
              30s auto-refresh
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Error state */}
        {error && (
          <div className="rounded-lg p-3 mb-3 font-mono text-xs bg-[#ff444410] border border-[#ff444430] text-[#ff4444]">
            {error}
          </div>
        )}

        {/* Loading state */}
        {!data && !error && (
          <div className="rounded-lg p-6 text-center bg-panel-alt">
            <span className="font-mono text-xs text-[#555]">
              Loading signal…
            </span>
          </div>
        )}

        {/* Loaded state */}
        {data && (
          <>
            {/* Primary signal hero */}
            <div
              className={`rounded-lg p-3 mb-4 flex items-center justify-between border ${heroBgClass(
                signalVariant
              )} ${heroBorderClass(signalVariant)}`}
            >
              <div>
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  Signal / Bias
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`font-mono text-xl font-bold tracking-wider ${heroTextClass(
                      signalVariant
                    )}`}
                  >
                    {signalText}
                  </span>
                  <Badge variant={biasBadgeVariant(data.bias)}>
                    {data.bias.replace(/_/g, " ")}
                  </Badge>
                </div>
              </div>
              <div className="text-right">
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  Signal Date
                </div>
                <div className="font-mono text-sm font-bold tabular-nums text-[#888]">
                  {data.date}
                </div>
                <div className="font-mono text-[9px] mt-0.5 text-[#333]">
                  {data.symbol}
                </div>
              </div>
            </div>

            {/* Price levels */}
            <div className="mb-3 space-y-0.5">
              <StatRow
                label="Entry Price (last close)"
                value={entry > 0 ? `$${entry.toFixed(2)}` : "--"}
                valueClassName="text-[#e0e0e0]"
              />
              <StatRow
                label={`Stop Level  (ATR × 0.70 = ${(atr * 0.7).toFixed(1)})`}
                value={computedStop > 0 ? `$${computedStop.toFixed(2)}` : "--"}
                sub={data.stop_level > 0 ? "engine" : "computed"}
                valueClassName="text-[#ff4444]"
              />
              <StatRow
                label={`Target 1  (ATR × 1.50 = ${(atr * 1.5).toFixed(1)})`}
                value={computedTarget1 > 0 ? `$${computedTarget1.toFixed(2)}` : "--"}
                sub={data.target_1 > 0 ? "engine" : "computed"}
                valueClassName="text-[#00ff88]"
              />
              {data.target_2 > 0 && (
                <StatRow
                  label="Target 2"
                  value={`$${data.target_2.toFixed(2)}`}
                  valueClassName="text-[#00d4ff]"
                />
              )}
            </div>

            {/* Indicator grid */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              {/* ATR */}
              <div className="rounded-lg p-2.5 bg-panel-alt border border-panel-border">
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  ATR
                </div>
                <div className="font-mono text-sm font-bold tabular-nums text-[#00d4ff]">
                  {atr.toFixed(2)} pts
                </div>
              </div>

              {/* Regime */}
              <div className="rounded-lg p-2.5 bg-panel-alt border border-panel-border">
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  Regime
                </div>
                <div className="font-mono text-sm font-bold text-[#00d4ff]">
                  {data.regime.replace(/_/g, " ")}
                </div>
              </div>

              {/* STC Value */}
              <div className="rounded-lg p-2.5 bg-panel-alt border border-panel-border">
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  STC Value
                </div>
                <div
                  className={`font-mono text-sm font-bold tabular-nums ${stcTextClass(data.stc_val)}`}
                >
                  {data.stc_val.toFixed(1)}
                  <span className="text-[9px] ml-1 text-[#555]">/ 100</span>
                </div>
                {/* STC bar */}
                <div className="mt-1 h-1 rounded-full overflow-hidden bg-panel-border">
                  <div
                    className={`h-full rounded-full transition-all ${stcBgClass(data.stc_val)}`}
                    style={{ width: `${Math.min(data.stc_val, 100)}%` }}
                  />
                </div>
              </div>

              {/* STC Signal + EMA Trend */}
              <div className="rounded-lg p-2.5 bg-panel-alt border border-panel-border">
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
                  STC Signal / EMA
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-xs font-bold capitalize text-[#e0e0e0]">
                    {data.stc_signal}
                  </span>
                  <span className="text-[#333]">/</span>
                  <span className="font-mono text-xs font-bold capitalize text-[#888]">
                    {data.ema_trend.replace(/_/g, " ")}
                  </span>
                </div>
              </div>
            </div>

            {/* Adaptive STC thresholds */}
            <div className="rounded-lg p-3 mb-3 font-mono text-[10px] leading-relaxed bg-panel-alt border border-panel-border text-[#666]">
              <div className="mb-1 text-[#444]">
                ADAPTIVE STC THRESHOLDS
              </div>
              <div className="flex gap-4 text-[#888]">
                <span>
                  Oversold:{" "}
                  <span className="font-bold text-[#00ff88]">
                    {data.adaptive_stc_os}
                  </span>
                </span>
                <span>
                  Overbought:{" "}
                  <span className="font-bold text-[#ff4444]">
                    {data.adaptive_stc_ob}
                  </span>
                </span>
              </div>
              <div className="mt-1 text-[#555]">
                {data.config}
              </div>
            </div>

            {/* Footer timestamp */}
            {lastFetch && (
              <div className="text-right">
                <span className="font-mono text-[9px] text-[#333]">
                  Last fetched: {lastFetch}
                </span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
