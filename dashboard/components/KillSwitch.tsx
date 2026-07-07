"use client";

import { useState, useEffect } from "react";
import { AlertTriangle, Power, ShieldOff, Check, X } from "lucide-react";
import { postEngine } from "@/lib/api";
import { soundAlertManager } from "@/lib/sound-alerts";
import { cn } from "@/lib/utils";

interface KillSwitchProps {
  isActive: boolean;
  reason?: string | null;
  onToggle: () => void;
}

type FeedbackState = "none" | "loading" | "success" | "error";

export function KillSwitch({ isActive, reason, onToggle }: KillSwitchProps) {
  const [loading, setLoading] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [confirmActivate, setConfirmActivate] = useState(false);
  const [typedConfirm, setTypedConfirm] = useState("");
  const [feedback, setFeedback] = useState<FeedbackState>("none");
  const [feedbackMessage, setFeedbackMessage] = useState("");

  useEffect(() => {
    if (feedback === "success" || feedback === "error") {
      const timer = setTimeout(() => setFeedback("none"), 5000);
      return () => clearTimeout(timer);
    }
  }, [feedback]);

  async function handleActivate() {
    if (typedConfirm !== "CONFIRM KILL") return;
    
    setLoading(true);
    setFeedback("loading");
    try {
      // Play alert sound
      soundAlertManager.killSwitchAlert().catch(() => {
        /* ignore audio errors */
      });

      await postEngine("/safety/kill-switch/activate", { reason: "manual_dashboard" });
      onToggle();
      setFeedback("success");
      setFeedbackMessage("Kill switch activated");
      setConfirmActivate(false);
      setTypedConfirm("");
    } catch (e) {
      console.error("Kill switch activate failed:", e);
      setFeedback("error");
      setFeedbackMessage("Failed to activate kill switch");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeactivate() {
    if (!confirmDeactivate) {
      setConfirmDeactivate(true);
      setTimeout(() => setConfirmDeactivate(false), 5000);
      return;
    }
    setLoading(true);
    setFeedback("loading");
    try {
      await postEngine("/safety/kill-switch/deactivate");
      onToggle();
      setFeedback("success");
      setFeedbackMessage("Kill switch deactivated");
    } catch (e) {
      console.error("Kill switch deactivate failed:", e);
      setFeedback("error");
      setFeedbackMessage("Failed to deactivate kill switch");
    } finally {
      setLoading(false);
      setConfirmDeactivate(false);
    }
  }

  if (isActive) {
    return (
      <div className="rounded-xl border border-bear/40 bg-bear/10 p-4 space-y-3">
        {/* Feedback banner */}
        {feedback === "success" && (
          <div className="rounded-lg bg-bull/20 border border-bull/40 p-3 flex items-center gap-2">
            <Check className="h-4 w-4 text-bull shrink-0" />
            <span className="text-xs text-bull font-medium">{feedbackMessage}</span>
          </div>
        )}
        {feedback === "error" && (
          <div className="rounded-lg bg-bear/30 border border-bear/50 p-3 flex items-center gap-2">
            <X className="h-4 w-4 text-bear shrink-0" />
            <span className="text-xs text-bear font-medium">{feedbackMessage}</span>
          </div>
        )}

        <div className="flex items-center gap-3 mb-1">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bear/20">
            <ShieldOff className="h-5 w-5 text-bear" aria-label="Kill switch active" />
          </div>
          <div>
            <p className="font-semibold text-bear" role="status">
              KILL SWITCH ACTIVE
            </p>
            {reason && (
              <p className="text-xs text-muted-foreground capitalize">
                {reason.replace(/_/g, " ")}
              </p>
            )}
          </div>
        </div>
        <button
          onClick={handleDeactivate}
          disabled={loading}
          aria-label="Deactivate kill switch and resume trading"
          className={cn(
            "w-full rounded-lg py-2 text-sm font-semibold transition-all ring-offset-2 focus-visible:ring-2 focus-visible:ring-bear",
            confirmDeactivate
              ? "bg-bear text-white animate-pulse"
              : "border border-bear/40 text-bear hover:bg-bear/10"
          )}
        >
          {loading
            ? "Processing…"
            : confirmDeactivate
            ? "⚠ CLICK AGAIN TO CONFIRM RESUME"
            : "Deactivate Kill Switch"}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Feedback banner */}
      {feedback === "success" && (
        <div className="rounded-lg bg-bull/20 border border-bull/40 p-3 flex items-center gap-2">
          <Check className="h-4 w-4 text-bull shrink-0" />
          <span className="text-xs text-bull font-medium">{feedbackMessage}</span>
        </div>
      )}
      {feedback === "error" && (
        <div className="rounded-lg bg-bear/30 border border-bear/50 p-3 flex items-center gap-2">
          <X className="h-4 w-4 text-bear shrink-0" />
          <span className="text-xs text-bear font-medium">{feedbackMessage}</span>
        </div>
      )}

      <div className="flex items-center gap-3 mb-1">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bull/10">
          <Power className="h-5 w-5 text-bull" />
        </div>
        <div>
          <p className="font-semibold text-foreground">Trading Active</p>
          <p className="text-xs text-muted-foreground">All systems operational</p>
        </div>
      </div>

      {confirmActivate ? (
        <div className="space-y-2 animate-in slide-in-from-top-2">
          <p className="text-[10px] font-bold text-bear uppercase tracking-tighter">
            Type "CONFIRM KILL" to halt all trading
          </p>
          <input
            autoFocus
            className="w-full rounded border border-bear bg-bear/5 px-2 py-1.5 text-xs font-mono uppercase focus:outline-none focus:ring-1 focus:ring-bear"
            value={typedConfirm}
            onChange={(e) => setTypedConfirm(e.target.value.toUpperCase())}
            placeholder="Type here..."
          />
          <div className="flex gap-2">
            <button
              onClick={handleActivate}
              disabled={loading || typedConfirm !== "CONFIRM KILL"}
              className="flex-1 rounded bg-bear py-1.5 text-xs font-bold text-white hover:bg-bear/90 disabled:opacity-30 transition-all"
            >
              HALT SYSTEM
            </button>
            <button
              onClick={() => {
                setConfirmActivate(false);
                setTypedConfirm("");
              }}
              className="px-3 rounded border border-border text-xs hover:bg-secondary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setConfirmActivate(true)}
          disabled={loading}
          aria-label="Activate emergency stop to halt all trading"
          className="w-full rounded-lg border border-bear/40 bg-bear/5 py-2 text-sm font-semibold text-bear transition-all hover:bg-bear hover:text-white disabled:opacity-50 ring-offset-2 focus-visible:ring-2 focus-visible:ring-bear"
        >
          {loading ? (
            "Processing…"
          ) : (
            <span className="flex items-center justify-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              EMERGENCY STOP
            </span>
          )}
        </button>
      )}
    </div>
  );
}
