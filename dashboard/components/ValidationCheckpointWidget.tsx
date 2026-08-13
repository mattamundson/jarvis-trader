"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchValidationCheckpoint, ValidationCheckpointResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export default function ValidationCheckpointWidget() {
  const { data, error, isLoading } = useSWR<ValidationCheckpointResponse>(
    "/paper/validation/checkpoint",
    fetchValidationCheckpoint,
    { refreshInterval: POLL_INTERVAL.MINUTE }
  );

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">Validation Progress</h2>
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">Validation Progress</h2>
        <p className="text-red-500">Error loading validation data</p>
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
    // max_drawdown_pct from the engine is already percent-scale (e.g. 12.06 == 12.06%) — do not multiply by 100 again.
    { key: "max_drawdown", label: "Max Drawdown", format: (v) => (v !== null ? `${v.toFixed(2)}%` : "N/A") },
  ];

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      {/* Title and Overall Status */}
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Validation Progress</h2>
        <Badge variant={overallVariant}>{data.overall_status}</Badge>
      </div>

      {/* Trade Count */}
      <div className="mb-6 text-center">
        <p className="text-3xl font-bold text-gray-900">{data.trade_count}</p>
        <p className="text-gray-600">/ 60 trades</p>
      </div>

      {/* Days Progress Bar */}
      <div className="mb-6">
        <div className="mb-2 flex justify-between">
          <span className="text-sm font-medium text-gray-700">30-Day Validation Window</span>
          <span className="text-sm text-gray-600">
            {data.days_elapsed} / 30 days
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-200">
          <div
            className="h-2 rounded-full bg-blue-500 transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* Gates Grid */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        {gates.map((gate) => {
          const gateData = data.gates[gate.key];
          if (!gateData) return null;

          const badgeVariant = getGateStatusVariant(gateData.status);
          const formattedValue = gate.format(gateData.current_value);
          const formattedTarget = gate.format(gateData.target_value);

          return (
            <div key={gate.key} className="rounded-lg border border-gray-100 bg-gray-50 p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium text-gray-700">{gate.label}</p>
                <Badge variant={badgeVariant}>{gateData.status}</Badge>
              </div>
              <p className="text-xl font-semibold text-gray-900">{formattedValue}</p>
              <p className="text-xs text-gray-600">Target: {formattedTarget}</p>
            </div>
          );
        })}
      </div>

      {/* Additional Info */}
      <div className="mt-6 border-t border-gray-200 pt-4">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-600">Trading Days</p>
            <p className="font-semibold text-gray-900">{data.trading_days}</p>
          </div>
          <div>
            <p className="text-gray-600">Days Remaining</p>
            <p className="font-semibold text-gray-900">{data.days_remaining}</p>
          </div>
          {data.validation_start && (
            <div className="col-span-2">
              <p className="text-gray-600">Validation Started</p>
              <p className="font-semibold text-gray-900">
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
