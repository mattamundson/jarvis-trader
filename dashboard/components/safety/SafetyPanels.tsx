"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Shield,
  ShieldOff,
} from "lucide-react";
import {
  activateKillSwitch,
  deactivateKillSwitch,
  type CircuitBreakerFull,
  type KillSwitchStatus,
} from "@/lib/settings-api";

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
      {title}
    </p>
  );
}

function ConfigRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number | boolean;
  mono?: boolean;
}) {
  const displayValue =
    typeof value === "boolean" ? (
      value ? (
        <span className="text-bull font-semibold">Enabled</span>
      ) : (
        <span className="text-bear font-semibold">Disabled</span>
      )
    ) : (
      <span className={`font-semibold text-foreground ${mono ? "font-mono" : ""}`}>
        {String(value)}
      </span>
    );

  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs">{displayValue}</span>
    </div>
  );
}

export function KillSwitchPanel({
  data,
  mutate,
}: {
  data: KillSwitchStatus | undefined;
  mutate: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [reasonInput, setReasonInput] = useState("");
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const isActive = data?.kill_switch_active ?? false;

  async function handleActivate() {
    setLoading(true);
    setFeedback(null);
    try {
      await activateKillSwitch(reasonInput || "Manual activation via dashboard");
      setFeedback("Kill switch activated.");
      setShowModal(false);
      setReasonInput("");
      mutate();
    } catch (e) {
      setFeedback("Failed to activate kill switch.");
      console.error(e);
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
    setFeedback(null);
    try {
      await deactivateKillSwitch();
      setFeedback("Kill switch deactivated. Trading may resume.");
      setConfirmDeactivate(false);
      mutate();
    } catch (e) {
      setFeedback("Failed to deactivate kill switch.");
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className={`rounded-xl border p-5 space-y-4 ${
        isActive ? "border-bear/40 bg-bear/5" : "border-border bg-card"
      }`}
    >
      <SectionHeader title="Kill Switch" />

      <div className="flex items-center gap-4">
        <div
          className={`flex h-14 w-14 items-center justify-center rounded-full ${
            isActive ? "bg-bear/20" : "bg-bull/10"
          }`}
        >
          {isActive ? (
            <ShieldOff className="h-7 w-7 text-bear" />
          ) : (
            <Shield className="h-7 w-7 text-bull" />
          )}
        </div>
        <div>
          <p className={`text-lg font-bold ${isActive ? "text-bear" : "text-bull"}`}>
            {isActive ? "KILL SWITCH ACTIVE" : "Trading Active"}
          </p>
          <p className="text-xs text-muted-foreground">
            {isActive
              ? data?.kill_switch_reason
                ? `Reason: ${data.kill_switch_reason.replace(/_/g, " ")}`
                : "All trading halted"
              : "All systems operational"}
          </p>
        </div>
      </div>

      {feedback && (
        <p className="text-xs rounded-lg bg-muted/60 px-3 py-2 text-muted-foreground">
          {feedback}
        </p>
      )}

      {isActive ? (
        <button
          onClick={handleDeactivate}
          disabled={loading}
          aria-label="Deactivate kill switch and resume trading"
          className={`w-full rounded-lg py-2.5 text-sm font-semibold transition-all disabled:opacity-50 ${
            confirmDeactivate
              ? "bg-bear text-white animate-pulse"
              : "border border-bear/40 text-bear hover:bg-bear/10"
          }`}
        >
          {loading
            ? "Processing..."
            : confirmDeactivate
            ? "CLICK AGAIN TO CONFIRM RESUME"
            : "Deactivate Kill Switch"}
        </button>
      ) : (
        <button
          onClick={() => setShowModal(true)}
          disabled={loading}
          className="w-full rounded-lg border border-bear/40 bg-bear/5 py-2.5 text-sm font-semibold text-bear transition-all hover:bg-bear hover:text-white disabled:opacity-50 flex items-center justify-center gap-2"
        >
          <AlertTriangle className="h-4 w-4" />
          ACTIVATE KILL SWITCH
        </button>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-bear/40 bg-card p-6 shadow-2xl space-y-4 mx-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-bear" />
              <h2 className="text-base font-bold text-bear">Activate Kill Switch</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              This will immediately halt all trading activity. You will need to
              manually deactivate it to resume.
            </p>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">
                Reason (optional)
              </label>
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-bear"
                placeholder="e.g. Market volatility, manual override..."
                value={reasonInput}
                onChange={(e) => setReasonInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleActivate();
                  if (e.key === "Escape") setShowModal(false);
                }}
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowModal(false);
                  setReasonInput("");
                }}
                className="flex-1 rounded-lg border border-border py-2 text-sm text-muted-foreground hover:bg-muted/50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleActivate}
                disabled={loading}
                className="flex-1 rounded-lg bg-bear py-2 text-sm font-semibold text-white hover:bg-bear/80 disabled:opacity-50 transition-colors"
              >
                {loading ? "Activating..." : "Activate"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function CircuitBreakerSummary({
  data,
}: {
  data: CircuitBreakerFull | undefined;
}) {
  if (!data) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-2 text-muted-foreground">
          <AlertTriangle className="h-4 w-4" />
          <span className="text-xs">Circuit breaker data unavailable</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`rounded-xl border p-5 space-y-3 ${
        data.kill_switch_active
          ? "border-bear/40 bg-bear/5"
          : !data.all_clear
          ? "border-warn/40 bg-warn/5"
          : "border-bull/30 bg-bull/5"
      }`}
    >
      <div className="flex items-center justify-between">
        <SectionHeader title="Circuit Breaker Status" />
        <div
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
            data.kill_switch_active
              ? "bg-bear/20 text-bear"
              : !data.all_clear
              ? "bg-warn/20 text-warn"
              : "bg-bull/20 text-bull"
          }`}
        >
          {data.kill_switch_active ? (
            <ShieldOff className="h-3 w-3" />
          ) : !data.all_clear ? (
            <AlertTriangle className="h-3 w-3" />
          ) : (
            <CheckCircle2 className="h-3 w-3" />
          )}
          {data.kill_switch_active
            ? "HALTED"
            : !data.all_clear
            ? "WARNING"
            : "All Clear"}
        </div>
      </div>

      <div className="space-y-0">
        <ConfigRow
          label="Daily P&L"
          value={`${data.daily_pnl >= 0 ? "+" : "-"}$${Math.abs(data.daily_pnl).toFixed(2)}`}
        />
        <ConfigRow
          label="Daily limit"
          value={`-$${Math.abs(data.daily_limit).toFixed(2)}`}
        />
        <ConfigRow
          label="Drawdown"
          value={`${(Math.abs(data.drawdown_pct) * 100).toFixed(2)}%`}
        />
        <ConfigRow label="Orders last minute" value={data.orders_last_minute} />
        <ConfigRow label="P&L source" value={data.pnl_source} mono />
      </div>
    </div>
  );
}
