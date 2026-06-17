"use client";
import { OfflineFallback } from "@/components/OfflineFallback";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface RiskConfig {
  max_contracts: number;
  risk_per_trade_pct: number;
  atr_stop_multiplier: number;
  atr_target_multiplier: number;
}

interface PositionSizingData {
  atr: number;
  riskConfig: RiskConfig;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** MES tick value: $1.25/tick, 4 ticks/point */
const TICK_VALUE = 1.25;
const TICKS_PER_POINT = 4;
/** Default account size for formula display */
const ACCOUNT_VALUE = 10_000;

function calcMetrics(data: PositionSizingData) {
  const { atr, riskConfig } = data;
  const { max_contracts, risk_per_trade_pct, atr_stop_multiplier, atr_target_multiplier } = riskConfig;

  const atrTicks = atr * TICKS_PER_POINT;
  const stopTicks = Math.round(atr * atr_stop_multiplier * TICKS_PER_POINT * 10) / 10;
  const targetTicks = Math.round(atr * atr_target_multiplier * TICKS_PER_POINT * 10) / 10;
  const stopDollar = stopTicks * TICK_VALUE;
  const targetDollar = targetTicks * TICK_VALUE;
  const riskPerContract = stopTicks * TICK_VALUE;
  const riskPerTrade = ACCOUNT_VALUE * risk_per_trade_pct;
  const computedContracts = riskPerContract > 0
    ? Math.floor(riskPerTrade / riskPerContract)
    : 0;
  const effectiveContracts = Math.min(computedContracts, max_contracts);

  return {
    atrTicks,
    stopTicks,
    targetTicks,
    stopDollar,
    targetDollar,
    riskPerContract,
    riskPerTrade,
    computedContracts,
    effectiveContracts,
  };
}

function contractBadgeVariant(n: number): "bull" | "info" | "warn" {
  if (n >= 2) return "bull";
  if (n === 1) return "info";
  return "warn";
}

function contractBadgeLabel(n: number): string {
  if (n >= 2) return "Adequate Sizing";
  if (n === 1) return "Conservative";
  return "Too Volatile";
}

// ── Stat Row ──────────────────────────────────────────────────────────────────

function StatRow({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5" style={{ borderBottom: "1px solid #111" }}>
      <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>
        {label}
      </span>
      <div className="text-right">
        <span className="font-mono text-sm font-bold tabular-nums" style={{ color: valueColor ?? "#e0e0e0" }}>
          {value}
        </span>
        {sub && (
          <span className="font-mono text-[10px] ml-2 tabular-nums" style={{ color: "#444" }}>
            {sub}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function PositionSizingWidget() {
  const [data, setData] = useState<PositionSizingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      // Fetch signal (ATR) and risk settings in parallel
      const [signalRes, settingsRes] = await Promise.all([
        fetchEngine(`/paper/mgc-signal`),
        fetchEngine(`/settings/risk`),
      ]);

      if (!signalRes.ok) throw new Error(`Signal fetch failed: ${signalRes.status}`);
      if (!settingsRes.ok) throw new Error(`Settings fetch failed: ${settingsRes.status}`);

      const signal = await signalRes.json();
      const settings = await settingsRes.json();

      const atr: number = typeof signal.atr === "number" ? signal.atr : 0;
      const cfg = settings.config ?? {};

      const riskConfig: RiskConfig = {
        max_contracts: typeof cfg.max_contracts === "number" ? cfg.max_contracts : 3,
        risk_per_trade_pct: typeof cfg.risk_per_trade_pct === "number" ? cfg.risk_per_trade_pct : 0.01,
        atr_stop_multiplier: typeof cfg.atr_stop_multiplier === "number" ? cfg.atr_stop_multiplier : 0.7,
        atr_target_multiplier: typeof cfg.atr_target_multiplier === "number" ? cfg.atr_target_multiplier : 1.5,
      };

      setData({ atr, riskConfig });
      setError(null);
      setLastFetch(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch position sizing data");
    }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 300_000);
    return () => clearInterval(timer);
  }, []);

  // Compute derived metrics when data is available
  const metrics = data ? calcMetrics(data) : null;
  const riskPct = data ? (data.riskConfig.risk_per_trade_pct * 100).toFixed(2) : "1.00";
  const stopMult = data ? data.riskConfig.atr_stop_multiplier.toFixed(2) : "0.70";
  const targetMult = data ? data.riskConfig.atr_target_multiplier.toFixed(2) : "1.50";
  const maxContractsCap = data ? data.riskConfig.max_contracts : 3;
  const effectiveContracts = metrics ? metrics.effectiveContracts : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-mono font-bold tracking-[0.15em] uppercase">
              Position Sizing
            </CardTitle>
            <p className="font-mono text-[10px] mt-0.5" style={{ color: "#555" }}>
              ATR-Based Risk Model
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={contractBadgeVariant(effectiveContracts)}>
              {contractBadgeLabel(effectiveContracts)}
            </Badge>
            {lastFetch && (
              <span className="font-mono text-[9px]" style={{ color: "#333" }}>
                {lastFetch}
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Error state */}
        {error && (
          <div
            className="rounded-lg p-3 mb-3 font-mono text-xs"
            style={{ backgroundColor: "#ff444410", border: "1px solid #ff444430", color: "#ff4444" }}
          >
            {error} — showing formula-only view
          </div>
        )}

        {/* Live metrics section */}
        {metrics && data && (
          <div className="mb-4 space-y-0.5">
            <StatRow
              label="Current ATR"
              value={`${data.atr.toFixed(1)} pts`}
              valueColor="#00d4ff"
            />
            <StatRow
              label="ATR in Ticks"
              value={`${metrics.atrTicks.toFixed(1)} ticks`}
              sub="(1 pt = 4 ticks)"
              valueColor="#00d4ff"
            />
            <StatRow
              label={`Stop Distance  (ATR × ${stopMult})`}
              value={`${metrics.stopTicks.toFixed(1)} ticks`}
              sub={`$${metrics.stopDollar.toFixed(2)}`}
              valueColor="#ff4444"
            />
            <StatRow
              label={`Target Distance  (ATR × ${targetMult})`}
              value={`${metrics.targetTicks.toFixed(1)} ticks`}
              sub={`$${metrics.targetDollar.toFixed(2)}`}
              valueColor="#00ff88"
            />
            <StatRow
              label="Risk / Contract"
              value={`$${metrics.riskPerContract.toFixed(2)}`}
              sub="(stop ticks × $1.25)"
              valueColor="#ffcc00"
            />
          </div>
        )}

        {/* Formula section — always visible */}
        <div
          className="rounded-lg p-3 mb-3 font-mono text-[10px] leading-relaxed"
          style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e", color: "#666" }}
        >
          <div className="mb-1" style={{ color: "#444" }}>
            MAX CONTRACTS FORMULA
          </div>
          <div style={{ color: "#888" }}>
            floor(risk_per_trade / (ATR × {stopMult} × $1.25))
          </div>
          <div className="mt-1" style={{ color: "#666" }}>
            risk_per_trade = account × {riskPct}% = ${(ACCOUNT_VALUE * (parseFloat(riskPct) / 100)).toFixed(0)} (on $10K)
          </div>
        </div>

        {/* Max Contracts result */}
        <div
          className="rounded-lg p-3 flex items-center justify-between"
          style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e" }}
        >
          <div>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Max Contracts
            </div>
            <div className="font-mono text-2xl font-bold tabular-nums" style={{ color: "#e0e0e0" }}>
              {effectiveContracts}
            </div>
          </div>
          <div className="text-right">
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Config Cap
            </div>
            <div className="font-mono text-xs" style={{ color: "#444" }}>
              max_contracts: {maxContractsCap}
            </div>
            <div className="font-mono text-[9px] mt-0.5" style={{ color: "#333" }}>
              via /settings/risk
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
