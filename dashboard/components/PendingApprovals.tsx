"use client";

import { APPROVALS_KEY, POLL_INTERVAL } from "@/lib/polling-config";

import React, { useCallback, useEffect } from "react";
import useSWR from "swr";
import {
  fetchEngine,
  PendingApproval,
  PendingApprovalsResponse,
  postApprovePending,
  postRejectPending,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Check, X, Clock, AlertTriangle } from "lucide-react";
import { useToast } from "@/lib/toast-context";

// ── Components ─────────────────────────────────────────────────────────────

export default function PendingApprovals() {
  const { addToast } = useToast();
  const { data, mutate, isLoading } = useSWR<PendingApprovalsResponse>(
    APPROVALS_KEY,
    () => fetchEngine<PendingApprovalsResponse>(`${APPROVALS_KEY}?limit=5`),
    { refreshInterval: POLL_INTERVAL.APPROVALS }
  );

  const pending = data?.pending || [];
  const activeApproval = pending[0]; // Keyboard shortcuts target the top one

  const handleApprove = useCallback(async (id: string) => {
    try {
      await postApprovePending(id, {});
      addToast("Trade approved successfully", "success");
      mutate();
    } catch (e) {
      addToast(`Approval failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    }
  }, [mutate, addToast]);

  const handleReject = useCallback(async (id: string) => {
    try {
      await postRejectPending(id, "rejected_by_dashboard");
      addToast("Trade rejected", "info");
      mutate();
    } catch (e) {
      addToast(`Rejection failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    }
  }, [mutate, addToast]);

  // Keyboard Shortcuts (Phase 4.3)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!activeApproval) return;
      
      // Ignore if user is typing in an input
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName || "")) return;

      if (e.key.toLowerCase() === "y") {
        handleApprove(activeApproval.approval_id);
      } else if (e.key.toLowerCase() === "n") {
        handleReject(activeApproval.approval_id);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeApproval, handleApprove, handleReject]);

  if (!isLoading && pending.length === 0) return null;

  return (
    <Card className="border-amber-500/20 bg-amber-500/5 shadow-lg animate-in fade-in slide-in-from-top-4">
      <CardHeader className="pb-3 flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-amber-600">
        <AlertTriangle className="w-4 h-4" />
        Pending Approvals ({pending.length})
        </CardTitle>
        <div className="flex items-center gap-1 text-[10px] font-mono text-muted-foreground">
        <Badge variant="neutral" className="text-[10px] px-1 h-4">Y</Badge> Approve
        <Badge variant="neutral" className="text-[10px] px-1 h-4 ml-1">N</Badge> Reject
        </div>
        </CardHeader>
        <CardContent className="space-y-4">
        {pending.map((app, idx) => (
        <div 
          key={app.approval_id} 
          className={`flex flex-col gap-3 p-3 rounded-lg border bg-card transition-all ${
            idx === 0 ? "border-amber-500 shadow-sm ring-1 ring-amber-500/20" : "border-border opacity-60"
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-bold font-mono">{app.symbol}</span>
              <Badge variant={app.action.toLowerCase() === "buy" ? "bull" : "bear"}>
                {app.action.toUpperCase()}
              </Badge>
              <span className="text-xs font-medium">{app.quantity}ct</span>
            </div>

              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="w-3 h-3" />
                {new Date(app.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>

            <div className="text-xs text-muted-foreground line-clamp-1 italic">
              {String(app.pipeline_snapshot?.summary || "No strategy reasoning provided")}
            </div>

            {idx === 0 && (
              <div className="flex gap-2 mt-1">
                <Button 
                  size="sm" 
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 h-8"
                  onClick={() => handleApprove(app.approval_id)}
                >
                  <Check className="w-3.5 h-3.5 mr-1" /> Approve
                </Button>
                <Button 
                  size="sm" 
                  variant="destructive"
                  className="flex-1 h-8"
                  onClick={() => handleReject(app.approval_id)}
                >
                  <X className="w-3.5 h-3.5 mr-1" /> Reject
                </Button>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
