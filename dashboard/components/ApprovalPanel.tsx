"use client";

import React, { useCallback, useState } from "react";
import useSWR from "swr";
import {
  fetchEngine,
  postEngine,
  PendingApproval,
  PendingApprovalsResponse,
  ApprovalActionResult,
  postApprovePending,
  postRejectPending,
} from "@/lib/api";

// Module-level SWR fetchers (not inside component to avoid re-render loops)
const fetchPendingApprovals = () =>
  fetchEngine<PendingApprovalsResponse>("/pipeline/pending-approvals?limit=50");

// Format ISO string as "X minutes ago" or "X hours ago"
function timeAgo(isoString: string): string {
  const now = new Date();
  const then = new Date(isoString);
  const diffMs = now.getTime() - then.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMins / 60);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return isoString;
}

// Check if approval has any provenance data
function hasProvenance(approval: PendingApproval): boolean {
  return !!(
    approval.regime ||
    approval.structure_position ||
    approval.bias ||
    approval.composite_score !== null ||
    approval.composite_score !== undefined ||
    approval.stc_contrib !== null ||
    approval.stc_contrib !== undefined ||
    approval.orb_contrib !== null ||
    approval.orb_contrib !== undefined ||
    approval.vwap_contrib !== null ||
    approval.vwap_contrib !== undefined ||
    approval.risk_pct_used !== null ||
    approval.risk_pct_used !== undefined
  );
}

// Regime badge with color coding
function RegimeBadge({ regime }: { regime: string }) {
  let classes = "inline-block text-xs font-medium px-2 py-0.5 rounded";

  switch (regime.toUpperCase()) {
    case "TRENDING_BULL":
    case "BULL":
      classes += " bg-green-100 text-green-800";
      break;
    case "TRENDING_BEAR":
    case "BEAR":
      classes += " bg-red-100 text-red-800";
      break;
    case "RANGING":
    case "RANGE":
      classes += " bg-yellow-100 text-yellow-800";
      break;
    default:
      classes += " bg-gray-100 text-gray-800";
  }

  return <span className={classes}>{regime}</span>;
}

// Conviction progress bar
function ConvictionBar({ riskPctUsed }: { riskPctUsed: number }) {
  const convictionPct = Math.min(100, Math.max(0, (riskPctUsed / 0.02) * 100));
  let barColor = "bg-red-500";

  if (convictionPct >= 80) {
    barColor = "bg-green-500";
  } else if (convictionPct >= 40) {
    barColor = "bg-amber-500";
  }

  return (
    <div className="w-full bg-gray-200 rounded h-2">
      <div
        className={`${barColor} h-2 rounded transition-all`}
        style={{ width: `${convictionPct}%` }}
      />
    </div>
  );
}

// Signal contribution pill
function SignalPill({
  label,
  active,
}: {
  label: string;
  active: boolean | null | undefined;
}) {
  const isActive = active === true;
  const classes = isActive
    ? "inline-block bg-blue-100 text-blue-800 text-xs font-medium px-2 py-0.5 rounded"
    : "inline-block bg-gray-100 text-gray-500 text-xs font-medium px-2 py-0.5 rounded";

  return <span className={classes}>{label}</span>;
}

// Countdown timer for 5-minute auto-expiry
function ExpiryTimer({ createdAt }: { createdAt: string }) {
  const [timeLeft, setTimeLeft] = React.useState<number>(0);

  React.useEffect(() => {
    const calculateTimeLeft = () => {
      const expiryTime = new Date(createdAt).getTime() + 5 * 60 * 1000;
      const now = new Date().getTime();
      return Math.max(0, Math.floor((expiryTime - now) / 1000));
    };

    setTimeLeft(calculateTimeLeft());
    const interval = setInterval(() => {
      const next = calculateTimeLeft();
      setTimeLeft(next);
      if (next <= 0) clearInterval(interval);
    }, 1000);

    return () => clearInterval(interval);
  }, [createdAt]);

  if (timeLeft <= 0) {
    return <span className="text-red-600 font-bold text-xs uppercase animate-pulse">Expired</span>;
  }

  const mins = Math.floor(timeLeft / 60);
  const secs = timeLeft % 60;
  const isUrgent = timeLeft < 60;

  return (
    <span className={`font-mono text-xs ${isUrgent ? "text-red-500 font-bold animate-pulse" : "text-amber-700"}`}>
      Expires in {mins}:{secs.toString().padStart(2, "0")}
    </span>
  );
}

export default function ApprovalPanel() {
  // SWR for pending approvals (5s refresh)
  const { data, error, isLoading, mutate } = useSWR<PendingApprovalsResponse>(
    "/pipeline/pending-approvals",
    fetchPendingApprovals,
    { refreshInterval: 5000 }
  );

  // Track loading state per approval (approval_id -> boolean)
  const [loadingApprovals, setLoadingApprovals] = useState<Record<string, boolean>>({});
  const [actionError, setActionError] = useState<string | null>(null);

  const handleApprove = useCallback(
    async (approval: PendingApproval) => {
      setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: true }));
      setActionError(null);
      try {
        await postApprovePending(approval.approval_id, {});
        // Refresh data after approval
        await mutate();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to approve";
        setActionError(msg);
      } finally {
        setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: false }));
      }
    },
    [mutate]
  );

  const handleReject = useCallback(
    async (approval: PendingApproval) => {
      setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: true }));
      setActionError(null);
      try {
        await postRejectPending(approval.approval_id, "rejected_by_trader");
        // Refresh data after rejection
        await mutate();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to reject";
        setActionError(msg);
      } finally {
        setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: false }));
      }
    },
    [mutate]
  );

  // Loading state
  if (isLoading) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
        <div className="inline-block">
          <div className="w-8 h-8 border-4 border-gray-300 border-t-blue-500 rounded-full animate-spin"></div>
        </div>
        <p className="text-gray-600 mt-3">Loading pending approvals...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6">
        <p className="text-red-800 font-semibold">Error loading approvals</p>
        <p className="text-red-600 text-sm mt-1">
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
      </div>
    );
  }

  const pending = data?.pending || [];
  const count = data?.count || 0;

  return (
    <div className="space-y-6">
      {/* Pending Approvals Section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Pending Approvals</h2>
          <span className="bg-amber-100 text-amber-800 text-sm font-medium px-3 py-1 rounded-full">
            {count}
          </span>
        </div>

        {actionError && (
          <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
            {actionError}
          </div>
        )}

        {pending.length === 0 ? (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
            <p className="text-gray-500">No pending approvals</p>
          </div>
        ) : (
          <div className="space-y-3">
            {pending.map((approval) => {
              const isLoading = loadingApprovals[approval.approval_id] || false;
              const actionLower = approval.action.toLowerCase();
              const isBuy = actionLower === "buy";

              return (
                <div
                  key={approval.approval_id}
                  className="bg-amber-50 border-l-4 border-amber-400 rounded-lg p-4 space-y-3"
                >
                  {/* Header row */}
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-sm font-semibold text-gray-700">
                        {approval.symbol}
                      </span>
                      <span
                        className={`inline-block text-xs font-bold px-2 py-1 rounded ${
                          isBuy
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-red-100 text-red-800"
                        }`}
                      >
                        {approval.action.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-xs text-gray-500">
                        {timeAgo(approval.created_at)}
                      </span>
                      <ExpiryTimer createdAt={approval.created_at} />
                    </div>
                  </div>

                  {/* Details row */}
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-gray-600">Quantity</p>
                      <p className="font-semibold text-gray-900">
                        {approval.quantity.toString()}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-600">Entry Price</p>
                      <p className="font-semibold text-gray-900">
                        {approval.entry_price !== null
                          ? approval.entry_price.toFixed(2)
                          : "TBD"}
                      </p>
                    </div>
                  </div>

                  {/* Signal Provenance Section */}
                  {hasProvenance(approval) && (
                    <div className="mt-3 pt-3 border-t border-amber-200 space-y-2">
                      <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                        Signal Provenance
                      </p>

                      {/* Regime badge */}
                      {approval.regime && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-600">Regime:</span>
                          <RegimeBadge regime={approval.regime} />
                        </div>
                      )}

                      {/* Bias chip */}
                      {approval.bias && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-600">Bias:</span>
                          <span className="inline-block bg-blue-100 text-blue-800 text-xs font-medium px-2 py-0.5 rounded">
                            {approval.bias}
                          </span>
                        </div>
                      )}

                      {/* Conviction bar */}
                      {approval.risk_pct_used !== null && approval.risk_pct_used !== undefined && (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-gray-600">Conviction:</span>
                            <span className="font-semibold text-gray-900">
                              {Math.round((approval.risk_pct_used / 0.02) * 100).toFixed(0)}%
                            </span>
                          </div>
                          <ConvictionBar riskPctUsed={approval.risk_pct_used} />
                        </div>
                      )}

                      {/* Signal pills */}
                      <div className="flex gap-1">
                        <SignalPill label="STC" active={approval.stc_contrib} />
                        <SignalPill label="ORB" active={approval.orb_contrib} />
                        <SignalPill label="VWAP" active={approval.vwap_contrib} />
                      </div>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2 pt-2">
                    <button
                      onClick={() => handleApprove(approval)}
                      disabled={isLoading}
                      className="flex-1 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white font-medium py-2 px-3 rounded transition-colors text-sm"
                    >
                      {isLoading ? "Processing..." : "Approve"}
                    </button>
                    <button
                      onClick={() => handleReject(approval)}
                      disabled={isLoading}
                      className="flex-1 bg-red-600 hover:bg-red-700 disabled:bg-red-400 text-white font-medium py-2 px-3 rounded transition-colors text-sm"
                    >
                      {isLoading ? "Processing..." : "Reject"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
