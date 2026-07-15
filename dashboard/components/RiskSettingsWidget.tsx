"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface RiskConfig {
  daily_loss_limit: number;
  max_drawdown_pct: number;
  max_contracts: number;
  risk_per_trade_pct: number;
  atr_stop_multiplier: number;
  atr_target_multiplier: number;
}

interface RiskSettingsResponse {
  config: RiskConfig;
  circuit_breakers: Record<string, unknown>;
  editable_keys: string[];
}

// ── Validation helpers ───────────────────────────────────────────────────────

type DotVariant = "bull" | "warn" | "bear";

function contractsDot(val: number): DotVariant {
  if (val <= 2) return "bull";
  if (val <= 4) return "warn";
  return "bear";
}

function dailyLossLimitDot(val: number): DotVariant {
  // Protective (high limit = less risk) → bull; anything under $200 → warn
  return val >= 200 ? "bull" : "warn";
}

const dotColors: Record<DotVariant, string> = {
  bull: "bg-bull",
  warn: "bg-warn",
  bear: "bg-bear",
};

function ValidationDot({ variant }: { variant: DotVariant }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${dotColors[variant]} shrink-0`}
      title={variant}
    />
  );
}

// ── Row component ────────────────────────────────────────────────────────────

function RiskRow({
  label,
  value,
  dot,
}: {
  label: string;
  value: string;
  dot?: DotVariant;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <div className="flex items-center gap-2">
        {dot && <ValidationDot variant={dot} />}
        {!dot && <span className="inline-block h-2 w-2 shrink-0" />}
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <span className="text-xs font-semibold font-mono text-foreground">
        {value}
      </span>
    </div>
  );
}

// ── Main Widget ──────────────────────────────────────────────────────────────

export function RiskSettingsWidget() {
  const [data, setData] = useState<RiskSettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchEngine<RiskSettingsResponse>("/settings/risk");
      setData(json);
      setLastRefreshed(new Date());
      setSecondsAgo(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch risk settings");
    } finally {
      setLoading(false);
    }
  }, []);

  // Single fetch on mount — no auto-refresh
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Tick the "seconds ago" counter every second
  useEffect(() => {
    if (!lastRefreshed) return;
    const interval = setInterval(() => {
      setSecondsAgo(Math.floor((Date.now() - lastRefreshed.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [lastRefreshed]);

  const cfg = data?.config ?? null;

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base font-semibold">
              Risk Configuration
            </CardTitle>
            <Badge variant="warn">Not Enforced</Badge>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </CardHeader>

      <CardContent className="space-y-1">
        <p className="text-[11px] rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-warn">
          Recorded in the database, not read by SafetyLayer — the engine enforces
          risk limits from engine/config.py / engine/.env at process start.
        </p>
        {/* Loading skeleton */}
        {loading && !cfg && (
          <div className="space-y-2 animate-pulse">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-8 w-full rounded-lg bg-muted" />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="rounded-lg bg-bear/10 border border-bear/20 px-3 py-2 text-xs text-bear">
            {error}
          </div>
        )}

        {/* Data grid */}
        {cfg && (
          <div>
            <RiskRow
              label="Max Contracts"
              value={String(cfg.max_contracts)}
              dot={contractsDot(cfg.max_contracts)}
            />
            <RiskRow
              label="Daily Loss Limit ($)"
              value={`$${cfg.daily_loss_limit.toLocaleString(undefined, {
                minimumFractionDigits: 0,
                maximumFractionDigits: 2,
              })}`}
              dot={dailyLossLimitDot(cfg.daily_loss_limit)}
            />
            <RiskRow
              label="Max Drawdown (%)"
              value={`${(cfg.max_drawdown_pct * 100).toFixed(1)}%`}
            />
            <RiskRow
              label="Risk Per Trade (%)"
              value={`${(cfg.risk_per_trade_pct * 100).toFixed(2)}%`}
            />
            <RiskRow
              label="ATR Stop Multiplier"
              value={cfg.atr_stop_multiplier.toFixed(2)}
            />
            <RiskRow
              label="ATR Target Multiplier"
              value={cfg.atr_target_multiplier.toFixed(2)}
            />
          </div>
        )}

        {/* Footer */}
        <div className="pt-2 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">
            {lastRefreshed
              ? `Last refreshed: ${secondsAgo}s ago`
              : "Not yet loaded"}
          </span>
          {data?.editable_keys && (
            <span className="text-[11px] text-muted-foreground">
              {data.editable_keys.length} editable keys
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
