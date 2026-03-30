"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

const MAX_CONTRACTS = 5;
const TICK_SIZE = 0.25;        // points
const TICK_VALUE = 1.25;       // USD per tick
const MULTIPLIER = 5;          // USD per point (MES)
const ATR_STOP_MULT = 0.70;    // stop = 0.70 × ATR
const RISK_PCT = 0.01;         // 1% risk per trade

interface SignalData {
  symbol?: string;
  atr?: number;
  account_value?: number;
  current_price?: number;
}

interface SafetyStatus {
  account_value?: number;
}

interface Calculated {
  accountValue: number;
  atr: number;
  stopDistancePts: number;
  stopDollarRisk: number;
  riskBudget: number;
  contracts: number;
}

function calcPositionSize(atr: number, accountValue: number): Calculated {
  const riskBudget = accountValue * RISK_PCT;
  const stopDistancePts = atr * ATR_STOP_MULT;
  // Round stop distance to nearest tick (0.25)
  const stopDistanceTicks = Math.round(stopDistancePts / TICK_SIZE);
  const stopDistancePtsRounded = stopDistanceTicks * TICK_SIZE;
  const stopDollarRisk = stopDistancePtsRounded * MULTIPLIER;
  const rawContracts = stopDollarRisk > 0 ? Math.floor(riskBudget / stopDollarRisk) : 0;
  const contracts = Math.min(rawContracts, MAX_CONTRACTS);

  return {
    accountValue,
    atr,
    stopDistancePts: stopDistancePtsRounded,
    stopDollarRisk,
    riskBudget,
    contracts,
  };
}

function fmt$(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function DataRow({
  label,
  value,
  bold = false,
  highlight = false,
}: {
  label: string;
  value: string;
  bold?: boolean;
  highlight?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between py-1.5 border-b border-border/50 last:border-0 ${
        highlight ? "rounded-lg bg-accent/5 px-2 -mx-2" : ""
      }`}
    >
      <span className={`text-xs ${bold ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
        {label}
      </span>
      <span className={`text-xs font-mono ${bold ? "font-bold text-foreground text-sm" : "font-semibold text-foreground"}`}>
        {value}
      </span>
    </div>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-6 w-full bg-muted rounded" />
      ))}
    </div>
  );
}

export function PositionSizerWidget() {
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [safetyStatus, setSafetyStatus] = useState<SafetyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    try {
      const [sigRes, safetyRes] = await Promise.allSettled([
        fetch(`${ENGINE_URL}/paper/mes-signal`),
        fetch(`${ENGINE_URL}/safety/status`),
      ]);

      if (sigRes.status === "fulfilled" && sigRes.value.ok) {
        const data: SignalData = await sigRes.value.json();
        setSignal(data);
      }

      if (safetyRes.status === "fulfilled" && safetyRes.value.ok) {
        const data: SafetyStatus = await safetyRes.value.json();
        setSafetyStatus(data);
      }

      setLastUpdated(new Date());
    } catch {
      // silently handle — show "awaiting" state
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, []);

  // Resolve account value: prefer signal data, fall back to safety status
  const accountValue =
    signal?.account_value ??
    safetyStatus?.account_value ??
    null;

  const atr = signal?.atr ?? null;
  const hasData = accountValue !== null && atr !== null && atr > 0;

  const calc: Calculated | null = hasData
    ? calcPositionSize(atr as number, accountValue as number)
    : null;

  return (
    <Card className="rounded-xl border border-border bg-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold text-foreground">
              Position Sizer
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Using MES futures — $5/pt, 0.25 tick
            </p>
          </div>
          <div className="flex items-center gap-2">
            {!loading && calc !== null && (
              <Badge variant={calc.contracts >= 1 ? "bull" : "warn"}>
                {calc.contracts >= 1 ? "WITHIN LIMITS" : "REDUCE RISK"}
              </Badge>
            )}
            {!loading && !hasData && (
              <Badge variant="neutral">NO DATA</Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-1">
        {loading ? (
          <SkeletonRows />
        ) : !hasData ? (
          <p className="text-xs text-muted-foreground py-4 text-center">
            Awaiting market data
          </p>
        ) : calc !== null ? (
          <div className="space-y-0">
            <DataRow
              label="Account Value"
              value={fmt$(calc.accountValue)}
            />
            <DataRow
              label="ATR (current)"
              value={`${calc.atr.toFixed(2)} pts`}
            />
            <DataRow
              label="Stop Distance"
              value={`${calc.stopDistancePts.toFixed(2)} pts (${ATR_STOP_MULT}x ATR)`}
            />
            <DataRow
              label="Dollar Risk / Contract"
              value={fmt$(calc.stopDollarRisk)}
            />
            <DataRow
              label="1% Risk Budget"
              value={fmt$(calc.riskBudget)}
            />
            <DataRow
              label="Recommended Contracts"
              value={String(calc.contracts)}
              bold
              highlight
            />
          </div>
        ) : null}

        {lastUpdated && !loading && (
          <p className="text-[10px] text-muted-foreground mt-3 text-right">
            Updated {lastUpdated.toLocaleTimeString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
