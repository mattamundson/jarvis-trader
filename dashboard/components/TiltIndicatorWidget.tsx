"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TiltStatus {
  is_tilted: boolean;
  tilt_score: number;
  severity: "none" | "caution" | "warning" | "critical";
  tilt_indicators: string[];
  position_size_multiplier: number;
  cooldown_until: string | null;
  recent_trade_count: number;
  consecutive_losses: number;
  rapid_trades_30min: number;
  recent_vetoes: number;
  // Disabled/not-initialized state
  enabled?: boolean;
  message?: string;
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const SEVERITY_DOT: Record<string, string> = {
  none: "bg-green-500",
  caution: "bg-yellow-400",
  warning: "bg-orange-400",
  critical: "bg-red-500",
};

const SEVERITY_TEXT: Record<string, string> = {
  none: "text-green-400",
  caution: "text-yellow-400",
  warning: "text-orange-400",
  critical: "text-red-400",
};

const SEVERITY_BORDER: Record<string, string> = {
  none: "",
  caution: "border-yellow-400/30",
  warning: "border-orange-400/40",
  critical: "border-red-500/50 bg-red-500/5",
};

const SEVERITY_LABEL: Record<string, string> = {
  none: "CALM",
  caution: "CAUTION",
  warning: "WARNING",
  critical: "CRITICAL",
};

const BADGE_VARIANT: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  none: "bull",
  caution: "warn",
  warning: "warn",
  critical: "bear",
};

function formatIndicator(raw: string): string {
  return raw
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function useCooldownCountdown(cooldownUntil: string | null): string | null {
  // We do a simple static computation — no setInterval needed for the
  // dashboard's 10-second refresh cadence.
  if (!cooldownUntil) return null;
  const until = new Date(cooldownUntil).getTime();
  const now = Date.now();
  const remainMs = until - now;
  if (remainMs <= 0) return null;
  const mins = Math.floor(remainMs / 60000);
  const secs = Math.floor((remainMs % 60000) / 1000);
  return `${mins}m ${secs}s`;
}

// ── Main Component ────────────────────────────────────────────────────────────

export function TiltIndicatorWidget() {
  const { data, error, isLoading } = useSWR<TiltStatus>(
    "/safety/tilt",
    fetcher,
    { refreshInterval: 10_000, revalidateOnFocus: true }
  );

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <Card className="p-4 space-y-3 animate-pulse">
        <div className="h-3 w-32 bg-muted rounded" />
        <div className="h-6 w-24 bg-muted rounded" />
        <div className="h-2 w-full bg-muted rounded-full" />
        <div className="flex gap-2">
          <div className="h-5 w-20 bg-muted rounded" />
          <div className="h-5 w-24 bg-muted rounded" />
        </div>
      </Card>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <Card className="p-4 border-muted/50">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
          TILT MONITOR
        </p>
        <p className="text-sm text-muted-foreground">
          Engine offline or unavailable
        </p>
      </Card>
    );
  }

  // ── Disabled / not initialized ────────────────────────────────────────────
  if (data.enabled === false) {
    return (
      <Card className="p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
          TILT MONITOR
        </p>
        <p className="text-sm text-muted-foreground">
          {data.message ?? "Disabled"}
        </p>
      </Card>
    );
  }

  const severity = data.severity ?? "none";
  const score = data.tilt_score ?? 0;
  const scorePct = Math.round(score * 100);
  const multiplierPct = Math.round((data.position_size_multiplier ?? 1) * 100);
  const cooldown = useCooldownCountdown(data.cooldown_until);
  const dotColor = SEVERITY_DOT[severity] ?? SEVERITY_DOT.none;
  const textColor = SEVERITY_TEXT[severity] ?? SEVERITY_TEXT.none;
  const borderClass = SEVERITY_BORDER[severity] ?? "";
  const badgeVariant = BADGE_VARIANT[severity] ?? "neutral";

  // Bar color for the tilt score bar
  const barColor =
    severity === "critical"
      ? "bg-red-500"
      : severity === "warning"
      ? "bg-orange-400"
      : severity === "caution"
      ? "bg-yellow-400"
      : "bg-green-500";

  return (
    <Card className={`p-4 space-y-3 ${borderClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          TILT MONITOR
        </p>
        <div className="flex items-center gap-2">
          {/* Severity dot */}
          <span
            className={`w-2.5 h-2.5 rounded-full ${dotColor} ${
              severity !== "none" ? "animate-pulse" : ""
            }`}
          />
          <Badge variant={badgeVariant}>
            {SEVERITY_LABEL[severity] ?? severity.toUpperCase()}
          </Badge>
        </div>
      </div>

      {/* Tilt score bar */}
      <div className="space-y-1">
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-muted-foreground">Tilt Score</span>
          <span className={`text-sm font-mono font-semibold ${textColor}`}>
            {scorePct}%
          </span>
        </div>
        <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${scorePct}%` }}
          />
        </div>
      </div>

      {/* Position size multiplier */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">Position Size</span>
        <span
          className={`text-sm font-mono font-semibold ${
            multiplierPct < 100
              ? multiplierPct === 0
                ? "text-red-400"
                : "text-yellow-400"
              : "text-green-400"
          }`}
        >
          {multiplierPct === 0 ? "HALTED" : `${multiplierPct}%`}
        </span>
      </div>

      {/* Active indicators */}
      {data.tilt_indicators && data.tilt_indicators.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Active Indicators
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.tilt_indicators.map((ind) => (
              <span
                key={ind}
                className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50"
              >
                {formatIndicator(ind)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Cooldown countdown */}
      {cooldown && (
        <div className="flex items-center gap-2 border-t border-border/40 pt-2">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <p className="text-xs text-red-400 font-medium">
            Cooldown: {cooldown} remaining
          </p>
        </div>
      )}

      {/* Stats footer */}
      <div className="grid grid-cols-3 gap-x-3 border-t border-border/40 pt-2">
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Losses</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.consecutive_losses ?? 0) >= 3 ? "text-yellow-400" : ""
          }`}>
            {data.consecutive_losses ?? 0}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Trades/30m</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.rapid_trades_30min ?? 0) >= 5 ? "text-orange-400" : ""
          }`}>
            {data.rapid_trades_30min ?? 0}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Vetoes</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.recent_vetoes ?? 0) >= 2 ? "text-yellow-400" : ""
          }`}>
            {data.recent_vetoes ?? 0}
          </p>
        </div>
      </div>
    </Card>
  );
}
