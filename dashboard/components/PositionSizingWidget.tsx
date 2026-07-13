"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine, type SafetyStatus } from "@/lib/api";
import { calcAtrPositionSize } from "@/lib/position-sizing";


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
  accountValue: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** MES tick value: $1.25/tick, 4 ticks/point */
const TICK_VALUE = 1.25;
const TICKS_PER_POINT = 4;
/** Fallback only — real value comes live from /safety/status portfolio_equity */
const ACCOUNT_VALUE_FALLBACK = 10_000;

function calcMetrics(data: PositionSizingData) {
  const { atr, riskConfig, accountValue } = data;
  const { max_contracts, risk_per_trade_pct, atr_stop_multiplier, atr_target_multiplier } = riskConfig;

  return calcAtrPositionSize({
    atr,
    accountValue,
    riskPct: risk_per_trade_pct,
    atrStopMultiplier: atr_stop_multiplier,
    atrTargetMultiplier: atr_target_multiplier,
    maxContracts: max_contracts,
    tickValue: TICK_VALUE,
    ticksPerPoint: TICKS_PER_POINT,
  });
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

/**
 * One concrete recommendation derived from which constraint is binding.
 * All numbers come straight from the shared ATR sizing result — nothing invented.
 */
function sizingRecommendation(
  computedContracts: number,
  effectiveContracts: number,
  maxContractsCap: number
): { text: string; tone: "emerald" | "amber" | "sky" } {
  if (computedContracts <= 0) {
    return {
      tone: "amber",
      text: `Recommend: skip or wait — current ATR leaves no contract inside the risk budget (0 fit). Re-check when volatility compresses.`,
    };
  }
  if (computedContracts > maxContractsCap) {
    return {
      tone: "sky",
      text: `Recommend: config cap is the binding limit — risk budget allows ${computedContracts}, capped to ${effectiveContracts}. Raise max_contracts (/settings/risk) to scale.`,
    };
  }
  return {
    tone: "emerald",
    text: `Recommend: size ${effectiveContracts} — volatility is the binding limit and the ${maxContractsCap}-contract cap has headroom.`,
  };
}

const RECO_TONE_CLASS: Record<"emerald" | "amber" | "sky", string> = {
  emerald: "text-emerald-300",
  amber: "text-amber-300",
  sky: "text-sky-300",
};

// ── Stat Row ──────────────────────────────────────────────────────────────────

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
        <span className={`font-mono text-sm font-bold tabular-nums ${valueClassName ?? "text-[#e0e0e0]"}`}>
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

export function PositionSizingWidget() {
  const [data, setData] = useState<PositionSizingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      // fetchEngine already returns parsed JSON (or throws on non-2xx) —
      // fetch signal (ATR), risk settings, and live account value in parallel.
      const [signal, settings, safetyStatus] = await Promise.all([
        fetchEngine<{ atr?: number }>(`/paper/mgc-signal`),
        fetchEngine<{ config?: Partial<RiskConfig> }>(`/settings/risk`),
        fetchEngine<SafetyStatus>(`/safety/status`).catch(() => null),
      ]);

      const atr: number = typeof signal.atr === "number" ? signal.atr : 0;
      const cfg = settings.config ?? {};

      const riskConfig: RiskConfig = {
        max_contracts: typeof cfg.max_contracts === "number" ? cfg.max_contracts : 3,
        risk_per_trade_pct: typeof cfg.risk_per_trade_pct === "number" ? cfg.risk_per_trade_pct : 0.01,
        atr_stop_multiplier: typeof cfg.atr_stop_multiplier === "number" ? cfg.atr_stop_multiplier : 0.7,
        atr_target_multiplier: typeof cfg.atr_target_multiplier === "number" ? cfg.atr_target_multiplier : 1.5,
      };

      const accountValue =
        typeof safetyStatus?.portfolio_equity === "number" && safetyStatus.portfolio_equity > 0
          ? safetyStatus.portfolio_equity
          : ACCOUNT_VALUE_FALLBACK;

      setData({ atr, riskConfig, accountValue });
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
  const accountValue = data ? data.accountValue : ACCOUNT_VALUE_FALLBACK;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-mono font-bold tracking-[0.15em] uppercase">
              Position Sizing
            </CardTitle>
            <p className="font-mono text-[10px] mt-0.5 text-[#555]">
              ATR-Based Risk Model
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={contractBadgeVariant(effectiveContracts)}>
              {contractBadgeLabel(effectiveContracts)}
            </Badge>
            {lastFetch && (
              <span className="font-mono text-[9px] text-[#333]">
                {lastFetch}
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Error state */}
        {error && (
          <div className="rounded-lg p-3 mb-3 font-mono text-xs bg-[#ff444410] border border-[#ff444430] text-[#ff4444]">
            {error} — showing formula-only view
          </div>
        )}

        {/* Live metrics section */}
        {metrics && data && (
          <div className="mb-4 space-y-0.5">
            <StatRow
              label="Current ATR"
              value={`${data.atr.toFixed(1)} pts`}
              valueClassName="text-[#00d4ff]"
            />
            <StatRow
              label="ATR in Ticks"
              value={`${metrics.atrTicks.toFixed(1)} ticks`}
              sub="(1 pt = 4 ticks)"
              valueClassName="text-[#00d4ff]"
            />
            <StatRow
              label={`Stop Distance  (ATR × ${stopMult})`}
              value={`${metrics.stopTicks.toFixed(1)} ticks`}
              sub={`$${metrics.stopDollar.toFixed(2)}`}
              valueClassName="text-[#ff4444]"
            />
            <StatRow
              label={`Target Distance  (ATR × ${targetMult})`}
              value={`${metrics.targetTicks.toFixed(1)} ticks`}
              sub={`$${metrics.targetDollar.toFixed(2)}`}
              valueClassName="text-[#00ff88]"
            />
            <StatRow
              label="Risk / Contract"
              value={`$${metrics.riskPerContract.toFixed(2)}`}
              sub="(stop ticks × $1.25)"
              valueClassName="text-[#ffcc00]"
            />
          </div>
        )}

        {/* Formula section — always visible */}
        <div className="rounded-lg p-3 mb-3 font-mono text-[10px] leading-relaxed bg-panel-alt border border-panel-border text-[#666]">
          <div className="mb-1 text-[#444]">
            MAX CONTRACTS FORMULA
          </div>
          <div className="text-[#888]">
            floor(risk_per_trade / (ATR × {stopMult} × $1.25))
          </div>
          <div className="mt-1 text-[#666]">
            risk_per_trade = account × {riskPct}% = ${(accountValue * (parseFloat(riskPct) / 100)).toFixed(0)}
            {" "}(on ${accountValue.toLocaleString()})
          </div>
        </div>

        {/* Max Contracts result */}
        <div className="rounded-lg p-3 flex items-center justify-between bg-panel-alt border border-panel-border">
          <div>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Max Contracts
            </div>
            <div className="font-mono text-2xl font-bold tabular-nums text-[#e0e0e0]">
              {effectiveContracts}
            </div>
          </div>
          <div className="text-right">
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Config Cap
            </div>
            <div className="font-mono text-xs text-[#444]">
              max_contracts: {maxContractsCap}
            </div>
            <div className="font-mono text-[9px] mt-0.5 text-[#333]">
              via /settings/risk
            </div>
          </div>
        </div>

        {/* Concrete recommendation — derived from the binding constraint */}
        {metrics && (
          (() => {
            const rec = sizingRecommendation(
              metrics.computedContracts,
              metrics.effectiveContracts,
              maxContractsCap
            );
            return (
              <p
                className={`mt-3 font-mono text-[10px] leading-snug ${RECO_TONE_CLASS[rec.tone]}`}
              >
                {rec.text}
              </p>
            );
          })()
        )}
      </CardContent>
    </Card>
  );
}
