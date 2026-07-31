"use client";

import React, { useCallback, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { Check, X, RefreshCw, ArrowLeft, AlertCircle } from "lucide-react";
import {
  getPendingApprovals,
  postApprovePending,
  postRejectPending,
  fetchEngine,
  type PendingApprovalRow,
  type SafetyStatus,
} from "@/lib/api";
import { useToast } from "@/lib/toast-context";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ActionableBoardWidget } from "@/components/ActionableBoardWidget";

const REFRESH_MS = 20_000;
/** Fallback base ONLY when the engine can't report live equity — never the
 *  authoritative figure. Live value comes from /safety/status portfolio_equity. */
const ACCOUNT_VALUE_FALLBACK = 10_000;

interface ApprovalConfirmDialog {
  isOpen: boolean;
  row: PendingApprovalRow | null;
  action: "approve" | "reject";
}

interface RiskSummary {
  positionSizePercent: number;
  marginImpactPercent: number;
  estimatedNotional: number;
  stopLevel: number | null;
}

export default function PendingApprovalsPage() {
  const { addToast } = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<Record<string, string>>({});
  const [overridePrice, setOverridePrice] = useState<Record<string, string>>({});
  const [confirmDialog, setConfirmDialog] = useState<ApprovalConfirmDialog>({
    isOpen: false,
    row: null,
    action: "approve",
  });

  const { data, error, isLoading, mutate } = useSWR(
    "pending-approvals",
    () => getPendingApprovals(100),
    { refreshInterval: REFRESH_MS }
  );

  // Live account base for the risk math on this screen. The percentages a human
  // approves against MUST reflect the real account, not a hardcoded literal —
  // /safety/status.portfolio_equity is the live figure; the fallback applies
  // only when the engine can't report it.
  const { data: safety } = useSWR<SafetyStatus>(
    "safety-status-for-approvals",
    () => fetchEngine<SafetyStatus>("/safety/status"),
    { refreshInterval: 60_000 }
  );
  const accountValueIsLive =
    typeof safety?.portfolio_equity === "number" && safety.portfolio_equity > 0;
  const accountValue = accountValueIsLive
    ? (safety!.portfolio_equity as number)
    : ACCOUNT_VALUE_FALLBACK;

  useWebSocket(undefined, (event) => {
    if (event.type === "pending_approval_created") {
      void mutate();
    }
  });

  const calculateRiskSummary = useCallback((row: PendingApprovalRow): RiskSummary => {
    const price = (row.entry_price ?? parseFloat(overridePrice[row.approval_id] || "0")) || 0;
    const qty = row.quantity || 0;
    const notional = price * qty;
    const portfolioValue = accountValue; // live equity (fallback only when engine offline)
    const positionSizePercent = (notional / portfolioValue) * 100;

    // Flat 5% heuristic (typical for futures micro contracts). No real
    // per-instrument margin-spec source is wired yet (engine/backtest/
    // contract_specs.py has multiplier/tick/commission but no margin field) —
    // this is a disclosed approximation, not a real margin lookup.
    const marginRequired = notional * 0.05;
    const marginImpactPercent = (marginRequired / portfolioValue) * 100;

    const snap = row.pipeline_snapshot ?? {};
    const signals = (snap as Record<string, unknown>).signals as Record<string, unknown> | undefined;
    const stopLevel = (signals?.stop_level as number) || null;

    return {
      positionSizePercent,
      marginImpactPercent,
      estimatedNotional: notional,
      stopLevel,
    };
  }, [overridePrice, accountValue]);

  const onApproveClick = useCallback((row: PendingApprovalRow) => {
    setConfirmDialog({
      isOpen: true,
      row,
      action: "approve",
    });
  }, []);

  const onRejectClick = useCallback((row: PendingApprovalRow) => {
    setConfirmDialog({
      isOpen: true,
      row,
      action: "reject",
    });
  }, []);

  const onConfirmAction = useCallback(async () => {
    if (!confirmDialog.row) return;

    const row = confirmDialog.row;
    setBusyId(row.approval_id);

    try {
      if (confirmDialog.action === "approve") {
        const raw = overridePrice[row.approval_id]?.trim();
        const ep = raw ? Number.parseFloat(raw) : undefined;
        const body =
          ep !== undefined && !Number.isNaN(ep) ? { entry_price: ep } : undefined;
        const out = await postApprovePending(row.approval_id, body);
        addToast(
          `Approved ${out.symbol} ${out.action} × ${out.quantity} @ ${out.entry_price?.toFixed(4) ?? "N/A"} — paper ${out.paper_trade_id?.slice(0, 8) ?? "N/A"}…`,
          "success"
        );
      } else {
        const reason = rejectReason[row.approval_id]?.trim() || undefined;
        await postRejectPending(row.approval_id, reason);
        addToast(`Rejected ${row.symbol} ${row.action} × ${row.quantity}`, "warning");
      }
      await mutate();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      addToast(msg, "error");
    } finally {
      setBusyId(null);
      setConfirmDialog({ isOpen: false, row: null, action: "approve" });
    }
  }, [confirmDialog, addToast, mutate, overridePrice, rejectReason]);

  const rows = data?.pending ?? [];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-background/95 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-6xl flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
            >
              <ArrowLeft className="h-4 w-4" />
              Dashboard
            </Link>
            <h1 className="text-lg font-semibold tracking-tight">Pending trade approvals</h1>
            {data !== undefined && (
              <Badge variant={rows.length ? "warn" : "neutral"}>{rows.length} pending</Badge>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={() => void mutate()} type="button">
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 space-y-6">
        {/* Live status board over recent directional decisions — where each
            signal stands vs the market right now. Display-only; approving/
            rejecting happens in the queue below. */}
        <ActionableBoardWidget />

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-foreground" />
            Loading pending approvals…
          </div>
        )}

        {error && (
          <Card className="border-bear/30 bg-bear/5">
            <CardContent className="flex items-start gap-3 pt-6">
              <AlertCircle className="h-5 w-5 text-bear flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-bear">Could not load approvals</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Is the engine running and reachable through the dashboard proxy? Check your connection and try refreshing.
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {!isLoading && !error && rows.length === 0 && (
          <Card className="border-border bg-card/50">
            <CardHeader>
              <CardTitle>All clear</CardTitle>
              <p className="text-sm text-muted-foreground">
                No trades are waiting for human approval. When the pipeline identifies a trade that
                requires human review, it will appear here.
              </p>
            </CardHeader>
          </Card>
        )}

        {rows.map((row) => {
          const snap = row.pipeline_snapshot ?? {};
          const summary = typeof snap.summary === "string" ? snap.summary : "";
          const fund = snap.fund_decision as Record<string, unknown> | undefined;
          const conv =
            typeof fund?.final_conviction === "number"
              ? Math.round(fund.final_conviction * 100)
              : null;
          const needsPrice = row.entry_price == null;
          const risk = calculateRiskSummary(row);

          const signals = (snap as Record<string, unknown>).signals as Record<string, unknown> | undefined;
          const stopLevel = (signals?.stop_level as number | undefined) ?? null;
          const targetLevel = (signals?.target_1 as number | undefined) ?? null;

          return (
            <Card key={row.approval_id} className="border-border">
              <CardHeader className="pb-3">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <CardTitle className="text-base">
                    {row.symbol}{" "}
                    <span className="text-muted-foreground font-normal">
                      {row.action.toUpperCase()} × {row.quantity}
                    </span>
                  </CardTitle>
                  <span className="text-xs text-muted-foreground font-mono">{row.created_at}</span>
                </div>
                {summary && (
                  <p className="text-sm text-muted-foreground line-clamp-2 mt-2">{summary}</p>
                )}
              </CardHeader>

              <CardContent className="space-y-4">
                {/* Price & Conviction */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground">Entry Price</p>
                    <p className="font-mono font-semibold">
                      {row.entry_price != null ? row.entry_price.toFixed(4) : "—"}
                    </p>
                  </div>
                  {conv !== null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Conviction</p>
                      <p className="font-semibold">{conv}%</p>
                    </div>
                  )}
                  {stopLevel !== null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Stop Level</p>
                      <p className="font-mono text-xs">{stopLevel.toFixed(4)}</p>
                    </div>
                  )}
                  {targetLevel !== null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Target</p>
                      <p className="font-mono text-xs">{targetLevel.toFixed(4)}</p>
                    </div>
                  )}
                </div>

                {/* Risk Summary */}
                <div className="bg-muted/30 rounded-md p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-muted-foreground">Risk Summary</p>
                    <p className="text-[10px] font-mono text-muted-foreground">
                      base ${accountValue.toLocaleString()}
                      {accountValueIsLive ? " (live)" : " (default — engine offline)"}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div>
                      <p className="text-muted-foreground">Position Size</p>
                      <p className="font-mono font-semibold">
                        {risk.positionSizePercent.toFixed(2)}%
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Est. Notional</p>
                      <p className="font-mono font-semibold">
                        ${risk.estimatedNotional.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <div className="flex items-center gap-1">
                        <p className="text-muted-foreground">Est. Margin Impact</p>
                        <Badge
                          variant="static"
                          className="text-[10px] px-1.5 py-0 leading-4 shrink-0"
                          title="Flat 5% of notional — a rough futures-margin approximation, not a real per-instrument margin lookup (no margin-spec source is wired yet)."
                        >
                          Static
                        </Badge>
                      </div>
                      <p
                        className={`font-mono font-semibold ${
                          risk.marginImpactPercent > 40 ? "text-bear" : ""
                        }`}
                      >
                        {risk.marginImpactPercent.toFixed(2)}%
                      </p>
                    </div>
                  </div>
                </div>

                {/* Approval ID and override inputs */}
                <div className="pt-2 space-y-3">
                  {needsPrice && (
                    <label className="flex flex-col gap-1 text-sm">
                      <span className="text-muted-foreground font-medium">
                        Override Entry Price (Required)
                      </span>
                      <input
                        type="number"
                        step="any"
                        className="rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                        placeholder="e.g. 72.5000"
                        value={overridePrice[row.approval_id] ?? ""}
                        onChange={(e) =>
                          setOverridePrice((p) => ({ ...p, [row.approval_id]: e.target.value }))
                        }
                      />
                    </label>
                  )}

                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground font-medium">
                      Rejection Reason (Optional)
                    </span>
                    <input
                      type="text"
                      className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                      placeholder="e.g. Waiting for clearer signal…"
                      value={rejectReason[row.approval_id] ?? ""}
                      onChange={(e) =>
                        setRejectReason((p) => ({ ...p, [row.approval_id]: e.target.value }))
                      }
                    />
                  </label>

                  <p className="text-xs text-muted-foreground font-mono pt-1">ID: {row.approval_id}</p>
                </div>

                {/* Action Buttons */}
                <div className="flex flex-col sm:flex-row gap-2 pt-2">
                  <Button
                    type="button"
                    variant="default"
                    disabled={
                      busyId === row.approval_id || (needsPrice && !overridePrice[row.approval_id]?.trim())
                    }
                    onClick={() => onApproveClick(row)}
                    className="flex-1 sm:flex-none"
                  >
                    <Check className="h-4 w-4 mr-1" />
                    Approve
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="border-bear/50 text-bear hover:bg-bear/10 flex-1 sm:flex-none"
                    disabled={busyId === row.approval_id}
                    onClick={() => onRejectClick(row)}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Reject
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </main>

      {/* Confirmation Dialog */}
      {confirmDialog.isOpen && confirmDialog.row && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setConfirmDialog({ isOpen: false, row: null, action: "approve" })}
        >
          <Card
            className="w-full max-w-sm border-border"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader>
              <CardTitle className="text-lg">
                {confirmDialog.action === "approve" ? "Approve Trade?" : "Reject Trade?"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="bg-muted/30 rounded-md p-3 space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Symbol</span>
                  <span className="font-semibold">{confirmDialog.row.symbol}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Action</span>
                  <span className="font-semibold">{confirmDialog.row.action.toUpperCase()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Quantity</span>
                  <span className="font-semibold">{confirmDialog.row.quantity}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Entry Price</span>
                  <span className="font-mono font-semibold">
                    {confirmDialog.row.entry_price?.toFixed(4) ??
                      overridePrice[confirmDialog.row.approval_id]?.trim() ??
                      "—"}
                  </span>
                </div>
              </div>

              {confirmDialog.action === "reject" && rejectReason[confirmDialog.row.approval_id] && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Reason:</p>
                  <p className="text-sm italic text-muted-foreground">
                    {rejectReason[confirmDialog.row.approval_id]}
                  </p>
                </div>
              )}

              <div className="flex gap-2 justify-end pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConfirmDialog({ isOpen: false, row: null, action: "approve" })}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant={confirmDialog.action === "approve" ? "default" : "destructive"}
                  disabled={busyId === confirmDialog.row.approval_id}
                  onClick={() => void onConfirmAction()}
                >
                  {confirmDialog.action === "approve" ? (
                    <>
                      <Check className="h-4 w-4 mr-1" />
                      Confirm Approval
                    </>
                  ) : (
                    <>
                      <X className="h-4 w-4 mr-1" />
                      Confirm Rejection
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
