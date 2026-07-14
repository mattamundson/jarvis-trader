"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Cpu } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


interface HealthData {
  version: string;
  live_trading: boolean;
  paper_mode: boolean;
  status: string;
}

interface RiskConfig {
  atr_stop_multiplier: number;
  atr_target_multiplier: number;
  risk_per_trade_pct: number;
}

interface EngineConfig {
  version: string;
  tradingMode: "Paper" | "Live";
  liveTradingEnabled: boolean;
  atrStopMultiplier: number;
  atrTargetMultiplier: number;
  riskPerTrade: number;
}

// Static defaults used when endpoints are unavailable
const STATIC_DEFAULTS: EngineConfig = {
  version: "1.1.0",
  tradingMode: "Paper",
  liveTradingEnabled: false,
  atrStopMultiplier: 0.7,
  atrTargetMultiplier: 1.5,
  riskPerTrade: 0.01,
};

function ConfigRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number | boolean;
  mono?: boolean;
}) {
  const displayValue =
    typeof value === "boolean" ? (
      value ? (
        <span className="text-bull font-semibold">Enabled</span>
      ) : (
        <span className="text-bear font-semibold">Disabled</span>
      )
    ) : (
      <span className={`font-semibold text-foreground ${mono ? "font-mono" : ""}`}>
        {String(value)}
      </span>
    );

  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs">{displayValue}</span>
    </div>
  );
}

export function EngineConfigCard() {
  const [config, setConfig] = useState<EngineConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [usingDefaults, setUsingDefaults] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch /health and /settings/risk in parallel
      const [healthRes, riskRes] = await Promise.allSettled([
        fetchEngine(`/health`, { cache: "no-store" }),
        fetchEngine(`/settings/risk`, { cache: "no-store" }),
      ]);

      let health: HealthData | null = null;
      let riskConfig: RiskConfig | null = null;

      if (healthRes.status === "fulfilled" && healthRes.value.ok) {
        health = (await healthRes.value.json()) as HealthData;
      }

      if (riskRes.status === "fulfilled" && riskRes.value.ok) {
        const riskData = (await riskRes.value.json()) as { config: RiskConfig };
        riskConfig = riskData.config;
      }

      if (!health && !riskConfig) {
        // Both endpoints failed — use static defaults
        setConfig(STATIC_DEFAULTS);
        setUsingDefaults(true);
        return;
      }

      setUsingDefaults(false);
      setConfig({
        version: health?.version ?? STATIC_DEFAULTS.version,
        tradingMode: health?.paper_mode ?? true ? "Paper" : "Live",
        liveTradingEnabled: health?.live_trading ?? false,
        atrStopMultiplier:
          riskConfig?.atr_stop_multiplier ?? STATIC_DEFAULTS.atrStopMultiplier,
        atrTargetMultiplier:
          riskConfig?.atr_target_multiplier ?? STATIC_DEFAULTS.atrTargetMultiplier,
        riskPerTrade: riskConfig?.risk_per_trade_pct ?? STATIC_DEFAULTS.riskPerTrade,
      });
    } catch (err) {
      setConfig(STATIC_DEFAULTS);
      setUsingDefaults(true);
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-accent" />
            <CardTitle>Engine Configuration</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="info">Read-Only</Badge>
            {usingDefaults && <Badge variant="neutral">Defaults</Badge>}
            <button
              onClick={fetchConfig}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted/50 disabled:opacity-50"
              title="Refresh config"
            >
              <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {loading && !config ? (
          <div className="space-y-2 animate-pulse">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="h-7 w-full bg-muted rounded" />
            ))}
          </div>
        ) : (
          <>
            {error && (
              <p className="text-xs rounded-lg bg-bear/10 text-bear px-3 py-2 mb-3">
                Engine unreachable — showing defaults.
              </p>
            )}

            {/* Section: Identity */}
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1 mt-1">
              Identity
            </p>
            <div className="mb-3">
              <ConfigRow
                label="Engine Version"
                value={config?.version ?? STATIC_DEFAULTS.version}
                mono
              />
              <ConfigRow
                label="Strategy"
                value="STC (Schaff Trend Cycle)"
              />
              <ConfigRow
                label="Trading Mode"
                value={config?.tradingMode ?? STATIC_DEFAULTS.tradingMode}
              />
              <ConfigRow
                label="Live Trading"
                value={config?.liveTradingEnabled ?? false}
              />
            </div>

            {/* Section: Strategy Parameters */}
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              Strategy Parameters
            </p>
            <div className="mb-3">
              <ConfigRow label="STC Oversold Threshold" value={15} />
              <ConfigRow label="STC Overbought Threshold" value={83} />
              <ConfigRow
                label="ATR Stop Multiplier"
                value={`${(config?.atrStopMultiplier ?? STATIC_DEFAULTS.atrStopMultiplier).toFixed(2)}x`}
              />
              <ConfigRow
                label="ATR Target Multiplier"
                value={`${(config?.atrTargetMultiplier ?? STATIC_DEFAULTS.atrTargetMultiplier).toFixed(2)}x`}
              />
              <ConfigRow
                label="Risk Per Trade"
                value={`${((config?.riskPerTrade ?? STATIC_DEFAULTS.riskPerTrade) * 100).toFixed(2)}%`}
              />
            </div>

            {/* Section: Filters */}
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              Filters
            </p>
            <div className="mb-3">
              <ConfigRow label="Regime Filter" value={true} />
              <ConfigRow label="Adaptive Regime" value={true} />
            </div>

            <p className="text-[11px] text-muted-foreground px-1 pt-1">
              Edit config via environment variables or{" "}
              <span className="font-mono text-[10px] bg-muted/60 px-1 py-0.5 rounded">
                PUT /settings/risk
              </span>
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
