"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Default config (used as fallback when all endpoints fail) ─────────────

const DEFAULT_CONFIG = {
  max_daily_loss: -500.0,
  max_drawdown_pct: 0.05,
  max_contracts: 5,
  risk_per_trade_pct: 0.01,
  atr_stop_multiplier: 0.7,
  atr_target_multiplier: 1.5,
  paper_trading: true,
  ib_host: "127.0.0.1",
  ib_port: 4002,
  symbols: ["MES", "MGC"],
  tick_value: 1.25,
  multiplier: 5.0,
};

// ── Types ─────────────────────────────────────────────────────────────────

interface RiskConfig {
  max_daily_loss?: number;
  max_drawdown_pct?: number;
  max_contracts?: number;
  risk_per_trade_pct?: number;
  atr_stop_multiplier?: number;
  atr_target_multiplier?: number;
  paper_trading?: boolean;
  ib_host?: string;
  ib_port?: number;
  symbols?: string[];
  tick_value?: number;
  multiplier?: number;
}

// ── Fetching logic ────────────────────────────────────────────────────────

async function fetchConfig(): Promise<{ config: RiskConfig; source: string } | null> {
  const endpoints = ["/risk/config", "/config", "/health"];

  for (const endpoint of endpoints) {
    try {
      const data = await fetchEngine<Record<string, unknown>>(endpoint, { cache: "no-store" });

      // /health may nest config; check for direct fields or nested
      if (
        typeof data.max_daily_loss === "number" ||
        typeof data.max_drawdown_pct === "number" ||
        typeof data.paper_trading === "boolean" ||
        typeof data.ib_host === "string"
      ) {
        return { config: data as RiskConfig, source: endpoint };
      }

      // nested under "config" key
      if (data.config && typeof data.config === "object") {
        return { config: data.config as RiskConfig, source: endpoint };
      }
    } catch {
      // swallow — try next endpoint
    }
  }

  return null;
}

// ── Sub-components ────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 mt-4 first:mt-0">
      {children}
    </p>
  );
}

function Row({
  label,
  value,
  mono = false,
  highlight,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  highlight?: "red";
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={[
          "text-xs font-semibold",
          mono ? "font-mono" : "",
          highlight === "red" ? "text-bear" : "text-foreground",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {value}
      </span>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2 animate-pulse p-1">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="h-6 w-full rounded bg-muted" />
      ))}
    </div>
  );
}

// ── Main Widget ────────────────────────────────────────────────────────────

export function RiskConfigDisplayWidget() {
  const [config, setConfig] = useState<RiskConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [usingDefaults, setUsingDefaults] = useState(false);

  const load = useCallback(async () => {
    const result = await fetchConfig();
    if (result) {
      setConfig(result.config);
      setUsingDefaults(false);
    } else {
      setConfig(DEFAULT_CONFIG);
      setUsingDefaults(true);
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void load();

    const interval = setInterval(() => {
      void load();
    }, 300_000); // 5 minutes

    return () => clearInterval(interval);
  }, [load]);

  // ── Derived display values ───────────────────────────────────────────────

  const maxDailyLoss = config?.max_daily_loss ?? DEFAULT_CONFIG.max_daily_loss;
  const maxDrawdownPct = config?.max_drawdown_pct ?? DEFAULT_CONFIG.max_drawdown_pct;
  const maxContracts = config?.max_contracts ?? DEFAULT_CONFIG.max_contracts;
  const riskPerTradePct = config?.risk_per_trade_pct ?? DEFAULT_CONFIG.risk_per_trade_pct;
  const atrStop = config?.atr_stop_multiplier ?? DEFAULT_CONFIG.atr_stop_multiplier;
  const atrTarget = config?.atr_target_multiplier ?? DEFAULT_CONFIG.atr_target_multiplier;
  const paperTrading = config?.paper_trading;
  const ibHost = config?.ib_host ?? DEFAULT_CONFIG.ib_host;
  const ibPort = config?.ib_port ?? DEFAULT_CONFIG.ib_port;
  const symbols = config?.symbols ?? DEFAULT_CONFIG.symbols;
  const tickValue = config?.tick_value ?? DEFAULT_CONFIG.tick_value;
  const multiplier = config?.multiplier ?? DEFAULT_CONFIG.multiplier;

  // Risk/reward ratio: target / stop
  const rrRatio =
    atrStop > 0
      ? `1:${(atrTarget / atrStop).toFixed(2)}`
      : "N/A";

  // Point value = tick_value / 0.25 * multiplier  (or tick_value * 4 for MES where tick=0.25)
  // Simplified: point value = multiplier * 1.0 (each full point = multiplier * tick_value / tick_size)
  // For MES: tick_value=1.25, tick_size=0.25pt → point_value = 1.25/0.25 = $5.00
  const tickSize = tickValue > 0 && multiplier > 0 ? tickValue / multiplier : 0.25;
  const pointValue = multiplier > 0 ? multiplier * (tickValue / (tickValue / multiplier === 0 ? 1 : 1)) : 5.0;
  // More direct: pointValue = tickValue * (1 / tickSize) = tickValue / tickSize
  const derivedPointValue = tickSize > 0 ? tickValue / tickSize : tickValue * 4;

  // Determine badge variant
  let badgeVariant: "info" | "bear" | "neutral" = "neutral";
  let badgeLabel = "CONFIG LOADED";
  if (paperTrading === true) {
    badgeVariant = "info";
    badgeLabel = "PAPER MODE";
  } else if (paperTrading === false) {
    badgeVariant = "bear";
    badgeLabel = "LIVE MODE";
  }

  return (
    <Card>
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between">
          <CardTitle>Risk Configuration</CardTitle>
          {!isLoading && (
            <Badge variant={badgeVariant}>{badgeLabel}</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-3">
        {isLoading ? (
          <LoadingSkeleton />
        ) : (
          <>
            {usingDefaults && (
              <div className="mb-3 rounded-lg bg-warn/10 border border-warn/30 px-3 py-2 text-xs text-warn font-medium">
                Showing defaults — config endpoint unavailable
              </div>
            )}

            {/* Two-column grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
              {/* ── Left column ─────────────────────────────────────── */}
              <div>
                {/* Section 1: Risk Limits */}
                <SectionLabel>Risk Limits</SectionLabel>
                <Row
                  label="Max Daily Loss"
                  value={
                    typeof maxDailyLoss === "number"
                      ? `-$${Math.abs(maxDailyLoss).toFixed(2)}`
                      : "N/A"
                  }
                />
                <Row
                  label="Max Drawdown"
                  value={
                    typeof maxDrawdownPct === "number"
                      ? `${(maxDrawdownPct * 100).toFixed(1)}%`
                      : "N/A"
                  }
                />
                <Row
                  label="Max Contracts"
                  value={
                    typeof maxContracts === "number" ? String(maxContracts) : "N/A"
                  }
                />
                <Row
                  label="Risk Per Trade"
                  value={
                    typeof riskPerTradePct === "number"
                      ? `${(riskPerTradePct * 100).toFixed(1)}%`
                      : "N/A"
                  }
                />

                {/* Section 2: ATR Parameters */}
                <SectionLabel>ATR Parameters</SectionLabel>
                <Row
                  label="Stop Multiplier"
                  value={
                    typeof atrStop === "number"
                      ? `${atrStop.toFixed(2)}x ATR`
                      : "N/A"
                  }
                />
                <Row
                  label="Target Multiplier"
                  value={
                    typeof atrTarget === "number"
                      ? `${atrTarget.toFixed(2)}x ATR`
                      : "N/A"
                  }
                />
                <Row label="Risk/Reward Ratio" value={rrRatio} />
              </div>

              {/* ── Right column ────────────────────────────────────── */}
              <div>
                {/* Section 3: Connection */}
                <SectionLabel>Connection</SectionLabel>
                <Row
                  label="Mode"
                  value={
                    paperTrading === true ? (
                      <Badge variant="info">PAPER TRADING</Badge>
                    ) : paperTrading === false ? (
                      <Badge variant="bear">LIVE TRADING</Badge>
                    ) : (
                      "N/A"
                    )
                  }
                />
                <Row
                  label="IB Host"
                  value={typeof ibHost === "string" ? ibHost : "N/A"}
                  mono
                />
                <Row
                  label="IB Port"
                  value={typeof ibPort === "number" ? String(ibPort) : "N/A"}
                  mono
                  highlight={ibPort === 4001 ? "red" : undefined}
                />
                <Row
                  label="Symbols"
                  value={
                    Array.isArray(symbols) && symbols.length > 0
                      ? symbols.join(", ")
                      : "N/A"
                  }
                />

                {/* Section 4: Instrument Specs */}
                <SectionLabel>Instrument Specs</SectionLabel>
                <Row
                  label="Tick Value"
                  value={
                    typeof tickValue === "number"
                      ? `$${tickValue.toFixed(2)}`
                      : "N/A"
                  }
                />
                <Row
                  label="Point Value"
                  value={
                    typeof derivedPointValue === "number"
                      ? `$${derivedPointValue.toFixed(2)}`
                      : "N/A"
                  }
                />
                <Row
                  label="Tick Size"
                  value={
                    typeof tickSize === "number"
                      ? `${tickSize.toFixed(2)} pts`
                      : "N/A"
                  }
                />
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
