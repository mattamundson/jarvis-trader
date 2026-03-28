"use client";

import { useState } from "react";
import { AlertTriangle, Power, ShieldOff } from "lucide-react";
import { postEngine } from "@/lib/api";
import { cn } from "@/lib/utils";

interface KillSwitchProps {
  isActive: boolean;
  reason?: string | null;
  onToggle: () => void;
}

export function KillSwitch({ isActive, reason, onToggle }: KillSwitchProps) {
  const [loading, setLoading] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  async function handleActivate() {
    setLoading(true);
    try {
      await postEngine("/safety/kill-switch/activate", { reason: "manual_dashboard" });
      onToggle();
    } catch (e) {
      console.error("Kill switch activate failed:", e);
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
    try {
      await postEngine("/safety/kill-switch/deactivate");
      onToggle();
    } catch (e) {
      console.error("Kill switch deactivate failed:", e);
    } finally {
      setLoading(false);
      setConfirmDeactivate(false);
    }
  }

  if (isActive) {
    return (
      <div className="rounded-xl border border-bear/40 bg-bear/10 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bear/20">
            <ShieldOff className="h-5 w-5 text-bear" />
          </div>
          <div>
            <p className="font-semibold text-bear">KILL SWITCH ACTIVE</p>
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
          className={cn(
            "w-full rounded-lg py-2 text-sm font-semibold transition-all",
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
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bull/10">
          <Power className="h-5 w-5 text-bull" />
        </div>
        <div>
          <p className="font-semibold text-foreground">Trading Active</p>
          <p className="text-xs text-muted-foreground">All systems operational</p>
        </div>
      </div>
      <button
        onClick={handleActivate}
        disabled={loading}
        className="w-full rounded-lg border border-bear/40 bg-bear/5 py-2 text-sm font-semibold text-bear transition-all hover:bg-bear hover:text-white disabled:opacity-50"
      >
        {loading ? "Processing…" : (
          <span className="flex items-center justify-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            EMERGENCY STOP
          </span>
        )}
      </button>
    </div>
  );
}
