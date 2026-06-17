"use client";

import useSWR from "swr";
import { fetchValidationCheckpoint, ValidationCheckpointResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export default function ValidationCheckpointWidget() {
  const { data, error, isLoading } = useSWR<ValidationCheckpointResponse>(
    "/paper/validation/checkpoint",
    fetchValidationCheckpoint,
    { refreshInterval: 60000 }
  );

  if (isLoading) {
    return (
      <div className="rounded-lg border border-[#1a1a2e] bg-[#0a0a0a] p-6">
        <h2 className="text-sm font-mono font-bold tracking-[0.15em] uppercase" style={{ color: "#00ff88" }}>
          Validation Progress
        </h2>
        <p className="text-xs font-mono mt-2" style={{ color: "#555" }}>Loading...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-[#1a1a2e] bg-[#0a0a0a] p-6">
        <h2 className="text-sm font-mono font-bold tracking-[0.15em] uppercase" style={{ color: "#00ff88" }}>
          Validation Progress
        </h2>
        <p className="text-xs font-mono mt-2" style={{ color: "#ff4444" }}>Error loading validation data</p>
      </div>
    );
  }

  // Determine overall badge variant
  const overallVariant = getStatusVariant(data.overall_status);

  // Progress bar calculation
  const progressPercent = Math.min((data.days_elapsed / 30) * 100, 100);

  // Gate formatting
  const gates: { key: string; label: string; format: (v: number | null) => string | number }[] = [
    { key: "profit_factor", label: "Profit Factor", format: (v) => (v !== null ? v.toFixed(2) : "N/A") },
    { key: "sharpe_ratio", label: "Sharpe Ratio", format: (v) => (v !== null ? v.toFixed(2) : "N/A") },
    { key: "win_rate", label: "Win Rate", format: (v) => (v !== null ? `${(v * 100).toFixed(1)}%` : "N/A") },
    { key: "trades", label: "Total Trades", format: (v) => (v !== null ? Math.round(v) : "0") },
    { key: "days", label: "Days Elapsed", format: (v) => (v !== null ? Math.round(v) : "0") },
    { key: "max_drawdown", label: "Max Drawdown", format: (v) => (v !== null ? `${(v * 100).toFixed(2)}%` : "N/A") },
  ];

  return (
    <div className="rounded-lg border border-[#1a1a2e] bg-[#0a0a0a] p-6">
      {/* Title and Overall Status */}
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-sm font-mono font-bold tracking-[0.15em] uppercase" style={{ color: "#00ff88" }}>
          Validation Progress
        </h2>
        <Badge variant={overallVariant}>{data.overall_status}</Badge>
      </div>

      {/* Trade Count */}
      <div className="mb-6 text-center">
        <p className="text-3xl font-bold font-mono" style={{ color: "#e0e0e0" }}>{data.trade_count}</p>
        <p className="text-xs font-mono" style={{ color: "#555" }}>/ 60 trades</p>
      </div>

      {/* Days Progress Bar */}
      <div className="mb-6">
        <div className="mb-2 flex justify-between">
          <span className="text-xs font-mono" style={{ color: "#888" }}>30-Day Validation Window</span>
          <span className="text-xs font-mono" style={{ color: "#555" }}>
            {data.days_elapsed} / 30 days
          </span>
        </div>
        <div className="h-1.5 w-full rounded-full" style={{ backgroundColor: "#1a1a2e" }}>
          <div
            className="h-1.5 rounded-full transition-all duration-300"
            style={{ width: `${progressPercent}%`, backgroundColor: "#00ff88" }}
          />
        </div>
      </div>

      {/* Gates Grid */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {gates.map((gate) => {
          const gateData = data.gates[gate.key];
          if (!gateData) return null;

          const badgeVariant = getGateStatusVariant(gateData.status);
          const formattedValue = gate.format(gateData.current_value);
          const formattedTarget = gate.format(gateData.target_value);

          return (
            <div key={gate.key} className="rounded-lg p-3" style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e" }}>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[10px] font-mono uppercase tracking-wider" style={{ color: "#888" }}>{gate.label}</p>
                <Badge variant={badgeVariant}>{gateData.status}</Badge>
              </div>
              <p className="text-lg font-bold font-mono" style={{ color: "#e0e0e0" }}>{formattedValue}</p>
              <p className="text-[10px] font-mono" style={{ color: "#555" }}>Target: {formattedTarget}</p>
            </div>
          );
        })}
      </div>

      {/* Additional Info */}
      <div className="mt-6 pt-4" style={{ borderTop: "1px solid #1a1a2e" }}>
        <div className="grid grid-cols-2 gap-4 text-xs font-mono">
          <div>
            <p style={{ color: "#555" }}>Trading Days</p>
            <p className="font-semibold" style={{ color: "#e0e0e0" }}>{data.trading_days}</p>
          </div>
          <div>
            <p style={{ color: "#555" }}>Days Remaining</p>
            <p className="font-semibold" style={{ color: "#e0e0e0" }}>{data.days_remaining}</p>
          </div>
          {data.validation_start && (
            <div className="col-span-2">
              <p style={{ color: "#555" }}>Validation Started</p>
              <p className="font-semibold" style={{ color: "#e0e0e0" }}>
                {new Date(data.validation_start).toLocaleDateString()}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function getStatusVariant(
  status: string
): "bull" | "bear" | "warn" | "info" | "neutral" {
  switch (status) {
    case "APPROVED":
      return "bull";
    case "ON_TRACK":
      return "bull";
    case "FAILING":
      return "bear";
    case "ACCUMULATING":
      return "neutral";
    default:
      return "info";
  }
}

function getGateStatusVariant(
  status: string
): "bull" | "bear" | "warn" | "info" | "neutral" {
  switch (status) {
    case "PASS":
      return "bull";
    case "FAIL":
      return "bear";
    case "INSUFFICIENT_DATA":
      return "neutral";
    default:
      return "info";
  }
}
