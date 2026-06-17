"use client";

import React, { useCallback, useState } from "react";
import { OfflineFallback } from "@/components/OfflineFallback";
import {
  PendingApproval,
  PendingApprovalsResponse,
  ApprovalActionResult,
  postApprovePending,
  postRejectPending,
} from "@/lib/api";
import { useEnginePendingApprovals } from "@/lib/engine-context";

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

// Regime badge
function RegimeBadge({ regime }: { regime: string }) {
  const upper = regime.toUpperCase();
  let color = "#888";
  let bg = "#1a1a2e";
  if (upper === "TRENDING_BULL" || upper === "BULL") { color = "#00ff88"; bg = "#00ff8810"; }
  else if (upper === "TRENDING_BEAR" || upper === "BEAR") { color = "#ff4444"; bg = "#ff444410"; }
  else if (upper === "RANGING" || upper === "RANGE") { color = "#ffaa00"; bg = "#ffaa0010"; }

  return (
    <span className="inline-block text-[10px] font-mono font-bold px-2 py-0.5 rounded"
      style={{ color, backgroundColor: bg, border: `1px solid ${color}30` }}>
      {regime}
    </span>
  );
}

// Conviction progress bar
function ConvictionBar({ riskPctUsed }: { riskPctUsed: number }) {
  const pct = Math.min(100, Math.max(0, (riskPctUsed / 0.02) * 100));
  const color = pct >= 80 ? "#00ff88" : pct >= 40 ? "#ffaa00" : "#ff4444";
  return (
    <div className="w-full rounded-full h-1.5" style={{ backgroundColor: "#1a1a2e" }}>
      <div className="h-1.5 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

// Signal contribution pill
function SignalPill({ label, active }: { label: string; active: boolean | null | undefined }) {
  const isActive = active === true;
  return (
    <span className="inline-block text-[10px] font-mono font-bold px-2 py-0.5 rounded"
      style={{
        color: isActive ? "#00ccff" : "#444",
        backgroundColor: isActive ? "#00ccff10" : "#0d0d1a",
        border: `1px solid ${isActive ? "#00ccff30" : "#1a1a2e"}`,
      }}>
      {label}
    </span>
  );
}

export default function ApprovalPanel() {
  const { pendingApprovals: data, isOffline, error, mutate } = useEnginePendingApprovals();
  const isLoading = !data && !error && !isOffline;

  const [loadingApprovals, setLoadingApprovals] = useState<Record<string, boolean>>({});
  const [actionError, setActionError] = useState<string | null>(null);

  const handleApprove = useCallback(async (approval: PendingApproval) => {
    setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: true }));
    setActionError(null);
    try {
      await postApprovePending(approval.approval_id, {});
      await mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: false }));
    }
  }, [mutate]);

  const handleReject = useCallback(async (approval: PendingApproval) => {
    setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: true }));
    setActionError(null);
    try {
      await postRejectPending(approval.approval_id, "rejected_by_trader");
      await mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to reject");
    } finally {
      setLoadingApprovals((prev) => ({ ...prev, [approval.approval_id]: false }));
    }
  }, [mutate]);

  // Loading state — dark
  if (isLoading) {
    return (
      <div className="rounded-lg p-4 text-center" style={{ backgroundColor: "#0d0d1a" }}>
        <p className="text-xs font-mono" style={{ color: "#555" }}>Loading approvals...</p>
      </div>
    );
  }

  // Error / offline state — dark, no raw API paths
  if (error) {
    return (
      <OfflineFallback variant="inline" message="Approvals unavailable — engine offline" />
    );
  }

  const pending = data?.pending || [];
  const count = data?.count || 0;

  if (pending.length === 0) {
    return (
      <div className="rounded-lg px-4 py-3 flex items-center gap-2" style={{ backgroundColor: "#0d0d1a" }}>
        <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: "#00ff88" }} />
        <p className="text-xs font-mono" style={{ color: "#555" }}>No pending approvals</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {actionError && (
        <div className="rounded-lg px-3 py-2 text-xs font-mono" style={{ backgroundColor: "#ff444410", color: "#ff4444", border: "1px solid #ff444430" }}>
          {actionError}
        </div>
      )}

      {pending.map((approval) => {
        const isApprovalLoading = loadingApprovals[approval.approval_id] || false;
        const isBuy = approval.action.toLowerCase() === "buy";

        return (
          <div
            key={approval.approval_id}
            className="rounded-lg p-4 space-y-3"
            style={{ backgroundColor: "#0d0d1a", border: "1px solid #ffaa0030", borderLeft: "3px solid #ffaa00" }}
          >
            {/* Header row */}
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold" style={{ color: "#e0e0e0" }}>
                  {approval.symbol}
                </span>
                <span
                  className="text-[10px] font-mono font-bold px-2 py-0.5 rounded"
                  style={{
                    color: isBuy ? "#00ff88" : "#ff4444",
                    backgroundColor: isBuy ? "#00ff8810" : "#ff444410",
                    border: `1px solid ${isBuy ? "#00ff8830" : "#ff444430"}`,
                  }}
                >
                  {approval.action.toUpperCase()}
                </span>
              </div>
              <span className="text-[10px] font-mono" style={{ color: "#555" }}>
                {timeAgo(approval.created_at)}
              </span>
            </div>

            {/* Details row */}
            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div>
                <p style={{ color: "#555" }}>Quantity</p>
                <p className="font-bold" style={{ color: "#e0e0e0" }}>{approval.quantity.toString()}</p>
              </div>
              <div>
                <p style={{ color: "#555" }}>Entry Price</p>
                <p className="font-bold" style={{ color: "#e0e0e0" }}>
                  {approval.entry_price !== null ? approval.entry_price.toFixed(2) : "TBD"}
                </p>
              </div>
            </div>

            {/* Signal Provenance */}
            {hasProvenance(approval) && (
              <div className="pt-3 space-y-2" style={{ borderTop: "1px solid #1a1a2e" }}>
                <p className="text-[10px] font-mono font-bold uppercase tracking-wider" style={{ color: "#555" }}>
                  Signal Provenance
                </p>
                {approval.regime && (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono" style={{ color: "#555" }}>Regime:</span>
                    <RegimeBadge regime={approval.regime} />
                  </div>
                )}
                {approval.bias && (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono" style={{ color: "#555" }}>Bias:</span>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded"
                      style={{ color: "#00ccff", backgroundColor: "#00ccff10", border: "1px solid #00ccff30" }}>
                      {approval.bias}
                    </span>
                  </div>
                )}
                {approval.risk_pct_used !== null && approval.risk_pct_used !== undefined && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-[10px] font-mono">
                      <span style={{ color: "#555" }}>Conviction:</span>
                      <span className="font-bold" style={{ color: "#e0e0e0" }}>
                        {Math.round((approval.risk_pct_used / 0.02) * 100)}%
                      </span>
                    </div>
                    <ConvictionBar riskPctUsed={approval.risk_pct_used} />
                  </div>
                )}
                <div className="flex gap-1">
                  <SignalPill label="STC" active={approval.stc_contrib} />
                  <SignalPill label="ORB" active={approval.orb_contrib} />
                  <SignalPill label="VWAP" active={approval.vwap_contrib} />
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => handleApprove(approval)}
                disabled={isApprovalLoading}
                className="flex-1 py-2 px-3 rounded text-xs font-mono font-bold transition-opacity disabled:opacity-40 min-h-[44px] min-w-[44px]"
                style={{ backgroundColor: "#00ff8820", color: "#00ff88", border: "1px solid #00ff8840" }}
              >
                {isApprovalLoading ? "..." : "Approve"}
              </button>
              <button
                onClick={() => handleReject(approval)}
                disabled={isApprovalLoading}
                className="flex-1 py-2 px-3 rounded text-xs font-mono font-bold transition-opacity disabled:opacity-40 min-h-[44px] min-w-[44px]"
                style={{ backgroundColor: "#ff444420", color: "#ff4444", border: "1px solid #ff444440" }}
              >
                {isApprovalLoading ? "..." : "Reject"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
