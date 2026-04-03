"use client";

import { useCallback, useState } from "react";
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
                    <span className="text-xs text-gray-500">
                      {timeAgo(approval.created_at)}
                    </span>
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
