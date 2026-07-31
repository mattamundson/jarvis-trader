"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import { postEngine } from "@/lib/api";
import { executionStatus } from "@/lib/executionPath";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Power,
  RefreshCw,
  Settings,
  Shield,
  ShieldOff,
  Wifi,
  WifiOff,
} from "lucide-react";
import {
  getKillSwitchStatus,
  getSafetyConfig,
  getIBGatewayStatus,
  getCircuitBreakers,
  activateKillSwitch,
  deactivateKillSwitch,
  resetDailyPnl,
  resolvePaperMode,
  type KillSwitchStatus,
  type SafetyConfig,
  type IBGatewayStatus,
  type CircuitBreakerFull,
} from "@/lib/settings-api";
import { NotificationTestPanel } from "@/components/NotificationTestPanel";
import { TradingScheduleCard } from "@/components/TradingScheduleCard";
import { RiskSettingsWidget } from "@/components/RiskSettingsWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { WhatsAppStatusCard } from "@/components/WhatsAppStatusCard";

// ── SWR fetchers ──────────────────────────────────────────────────────────

const fetchKillSwitch = () => getKillSwitchStatus();
const fetchConfig = () => getSafetyConfig();
const fetchGateway = () => getIBGatewayStatus();
const fetchCircuitBreakers = () => getCircuitBreakers();

// ── Helpers ───────────────────────────────────────────────────────────────

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

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

// ── Kill Switch Panel ─────────────────────────────────────────────────────

function KillSwitchPanel({
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
        isActive
          ? "border-bear/40 bg-bear/5"
          : "border-border bg-card"
      }`}
    >
      <SectionHeader title="Kill Switch" />

      {/* Status indicator */}
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
          <p
            className={`text-lg font-bold ${
              isActive ? "text-bear" : "text-bull"
            }`}
          >
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

      {/* Feedback message */}
      {feedback && (
        <p className="text-xs rounded-lg bg-muted/60 px-3 py-2 text-muted-foreground">
          {feedback}
        </p>
      )}

      {/* Toggle button */}
      {isActive ? (
        <button
          onClick={handleDeactivate}
          disabled={loading}
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

      {/* Activation modal */}
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

// ── Risk Parameters Panel ─────────────────────────────────────────────────

function RiskParametersPanel({ data }: { data: SafetyConfig | undefined }) {
  if (!data) {
    return (
      <div className="rounded-xl border border-border bg-card p-5 animate-pulse">
        <div className="h-4 w-32 bg-muted rounded mb-4" />
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-4 w-full bg-muted rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-2">
      <SectionHeader title="Risk Parameters" />
      <div className="rounded-lg bg-muted/30 px-3 py-1 text-[10px] text-muted-foreground font-mono mb-2">
        Read-only — edit via .env file and restart engine
      </div>
      <div className="space-y-0">
        <ConfigRow
          label="Daily loss limit"
          value={`-${pct(data.max_daily_loss_pct)}`}
        />
        <ConfigRow
          label="Max drawdown"
          value={`-${pct(data.max_drawdown_pct)}`}
        />
        <ConfigRow
          label="Max position size"
          value={pct(data.max_position_size_pct)}
        />
        <ConfigRow
          label="Max contracts per instrument"
          value={data.max_contracts_per_instrument}
        />
        <ConfigRow
          label="Max overnight contracts"
          value={data.max_overnight_contracts}
        />
        <ConfigRow
          label="Max orders per minute"
          value={data.max_orders_per_minute}
        />
        <ConfigRow
          label="Max single order value"
          value={`$${data.max_single_order_value.toLocaleString()}`}
        />
        <ConfigRow
          label="Max margin utilization"
          value={pct(data.max_margin_utilization)}
        />
        <ConfigRow
          label="Live trading"
          value={data.live_trading_enabled}
        />
        <ConfigRow
          label="Require human approval"
          value={data.require_human_approval}
        />
      </div>
    </div>
  );
}

// ── IB Gateway Panel ──────────────────────────────────────────────────────

function IBGatewayPanel({
  data,
  config,
}: {
  data: IBGatewayStatus | undefined;
  config: SafetyConfig | undefined;
}) {
  // D3-01: `ibkr_execution_connected` / `ibkr_connected` are cached connector
  // booleans that go true the instant the TCP socket to the paper Gateway is
  // up — they say nothing about whether an order can reach a broker. The
  // engine's own /health also exposes an honest `execution_path` probe
  // (`{ simulated, broker_ack, detail }`) that can read `simulated: true`
  // while both legacy booleans still read true. Route through
  // executionStatus() so this surface reflects the honest state, not the
  // legacy connector flags.
  const exec = executionStatus(data);
  const connected = exec.brokerReachable;
  // GT-13: resolvePaperMode() prefers the /health-derived paper_mode (live
  // IB Gateway connection) over the config snapshot, and flags disagreement
  // instead of letting a stale `ibkr_paper_mode: false` silently win via `??`.
  const { paperMode, mismatch: paperModeMismatch } = resolvePaperMode(config, data);
  const configPaperMode = config?.ibkr_paper_mode;
  const healthPaperMode = data?.paper_mode;

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      <SectionHeader title="IB Gateway Connection" />

      <div className="flex items-center gap-4">
        <div
          className={`flex h-12 w-12 items-center justify-center rounded-full ${
            exec.tone === "bull" ? "bg-bull/10" : exec.tone === "warn" ? "bg-warn/10" : "bg-muted"
          }`}
          title={exec.detail}
        >
          {connected ? (
            <Wifi className="h-6 w-6 text-bull" />
          ) : (
            <WifiOff className={`h-6 w-6 ${exec.tone === "warn" ? "text-warn" : "text-muted-foreground"}`} />
          )}
        </div>
        <div>
          <p
            className={`font-semibold ${
              exec.tone === "bull" ? "text-bull" : exec.tone === "warn" ? "text-warn" : "text-muted-foreground"
            }`}
            title={exec.detail}
          >
            {exec.label}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            {paperMode && (
              <span className="rounded border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[10px] font-semibold text-warn">
                PAPER
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              Port {config?.ibkr_port ?? "—"} ({paperMode ? "paper trading only" : "live"})
            </span>
          </div>
        </div>
      </div>

      {paperModeMismatch && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-xs text-bear"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            Paper/live mode disagreement: config reports{" "}
            <strong>{configPaperMode ? "paper" : "live"}</strong>, but the live IB
            Gateway connection (/health) reports{" "}
            <strong>{healthPaperMode ? "paper" : "live"}</strong>. Displaying the
            /health-derived value below — verify before trading.
          </span>
        </div>
      )}

      <div className="space-y-0">
        <ConfigRow label="Host" value={config?.ibkr_host ?? "—"} mono />
        <ConfigRow label="Port" value={config?.ibkr_port ?? "—"} mono />
        <ConfigRow label="Client ID" value={config?.ibkr_client_id ?? "—"} mono />
        <ConfigRow label="Mode" value={paperMode ? "Paper trading only" : "Live trading"} />
        <ConfigRow label="Live trading locked" value={!(config?.live_trading_enabled ?? false)} />
      </div>

      {data?.account_id && (
        <div className="rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground font-mono">
          Account: {data.account_id}
        </div>
      )}
    </div>
  );
}

// ── Circuit Breaker Summary ───────────────────────────────────────────────

function CircuitBreakerSummary({ data }: { data: CircuitBreakerFull | undefined }) {
  if (!data) return null;

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
          value={`${data.daily_pnl >= 0 ? "+" : ""}$${data.daily_pnl.toFixed(2)}`}
        />
        <ConfigRow
          label="Daily limit"
          value={`-$${Math.abs(data.daily_limit).toFixed(2)}`}
        />
        <ConfigRow
          label="Drawdown"
          value={`${(Math.abs(data.drawdown_pct) * 100).toFixed(2)}%`}
        />
        <ConfigRow
          label="Orders last minute"
          value={data.orders_last_minute}
        />
        <ConfigRow label="P&L source" value={data.pnl_source} mono />
      </div>
    </div>
  );
}

// ── Notifications Panel ───────────────────────────────────────────────────

function NotificationsPanel() {
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  async function handleMorningBriefing() {
    setSending(true);
    setFeedback(null);
    try {
      const data = await postEngine<{ sent: boolean; detail?: string }>(
        "/notifications/morning-briefing"
      );
      if (data.sent) {
        setFeedback("Morning briefing sent via WhatsApp.");
      } else {
        setFeedback("WhatsApp not configured or send failed.");
      }
    } catch (e) {
      setFeedback("Request failed — engine may be offline.");
      console.error(e);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      <SectionHeader title="Notifications" />

      {feedback && (
        <p className="text-xs rounded-lg bg-muted/60 px-3 py-2 text-muted-foreground">
          {feedback}
        </p>
      )}

      <div className="space-y-2">
        <button
          onClick={handleMorningBriefing}
          disabled={sending}
          className="w-full rounded-lg border border-accent/40 bg-accent/5 py-2 text-sm font-medium text-accent transition-all hover:bg-accent/10 disabled:opacity-50"
        >
          {sending ? "Sending..." : "Send Morning Briefing Now"}
        </button>

        <p className="text-[11px] text-muted-foreground px-1">
          Sends the WhatsApp pre-market briefing immediately. Normally fires
          automatically at 8:25 AM CT on trading days.
        </p>
      </div>
    </div>
  );
}

// ── Session Controls ──────────────────────────────────────────────────────

function SessionControls({ mutateAll }: { mutateAll: () => void }) {
  const [resettingPnl, setResettingPnl] = useState(false);
  const [pnlFeedback, setPnlFeedback] = useState<string | null>(null);

  async function handleResetPnl() {
    const confirmed = window.confirm(
      "Reset the daily P&L counter to zero?\n\nThis only affects the in-memory counter — it does NOT affect SQLite trade records."
    );
    if (!confirmed) return;
    setResettingPnl(true);
    setPnlFeedback(null);
    try {
      await resetDailyPnl();
      setPnlFeedback("Daily P&L counter reset.");
      mutateAll();
    } catch (e) {
      setPnlFeedback("Failed to reset P&L counter.");
      console.error(e);
    } finally {
      setResettingPnl(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      <SectionHeader title="Session Controls" />

      {pnlFeedback && (
        <p className="text-xs rounded-lg bg-muted/60 px-3 py-2 text-muted-foreground">
          {pnlFeedback}
        </p>
      )}

      <div className="space-y-2">
        <button
          onClick={handleResetPnl}
          disabled={resettingPnl}
          className="w-full rounded-lg border border-warn/40 bg-warn/5 py-2 text-sm font-medium text-warn transition-all hover:bg-warn/10 disabled:opacity-50"
        >
          {resettingPnl ? "Resetting..." : "Reset Daily P&L Counter"}
        </button>

        <p className="text-[11px] text-muted-foreground px-1">
          Resets the in-memory P&L counter only. Does not affect persisted
          trade records in SQLite.
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const {
    data: killSwitchData,
    mutate: mutateKillSwitch,
    isLoading: loadingKS,
  } = useSWR<KillSwitchStatus>("settings/kill-switch", fetchKillSwitch, {
    refreshInterval: 5_000,
  });

  const { data: configData } = useSWR<SafetyConfig>(
    "settings/config",
    fetchConfig,
    { refreshInterval: 60_000 }
  );

  const { data: gatewayData } = useSWR<IBGatewayStatus>(
    "settings/gateway",
    fetchGateway,
    { refreshInterval: 10_000 }
  );

  const { data: cbData, mutate: mutateCb } = useSWR<CircuitBreakerFull>(
    "settings/circuit-breakers",
    fetchCircuitBreakers,
    { refreshInterval: 5_000 }
  );

  const mutateAll = useCallback(() => {
    mutateKillSwitch();
    mutateCb();
  }, [mutateKillSwitch, mutateCb]);

  const isKilled = killSwitchData?.kill_switch_active ?? false;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a
                href="/"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Dashboard
              </a>
              <a
                href="/analysis"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Analysis
              </a>
              <a
                href="/backtest"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Backtest
              </a>
              <a
                href="/performance"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Performance
              </a>
              <a
                href="/validation"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Validation
              </a>
              <a
                href="/journal"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Journal
              </a>
              <a
                href="/watchlist"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Watchlist
              </a>
              <a
                href="/scorecard"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Scorecard
              </a>
              <a
                href="/settings"
                className="text-xs text-foreground font-semibold border-b border-accent pb-0.5"
              >
                Settings
              </a>
              <a
                href="/health"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Health
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {isKilled && (
              <div className="flex items-center gap-1.5 rounded-full bg-bear/10 border border-bear/30 px-2.5 py-1 text-xs font-semibold text-bear">
                <AlertTriangle className="h-3.5 w-3.5" />
                KILL SWITCH
              </div>
            )}
            {!loadingKS && !isKilled && (
              <div className="flex items-center gap-1.5 text-xs text-bull">
                <Power className="h-3.5 w-3.5" />
                <span>Trading active</span>
              </div>
            )}
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground opacity-40" />
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
        {/* Risk Settings Widget — live read-only config overview */}
        <WidgetErrorBoundary name="Risk Settings">
          <RiskSettingsWidget />
        </WidgetErrorBoundary>

        {/* Page title */}
        <div className="flex items-center gap-3">
          <Settings className="h-5 w-5 text-muted-foreground" />
          <div>
            <h2 className="text-lg font-bold text-foreground">
              Risk &amp; System Configuration
            </h2>
            <p className="text-xs text-muted-foreground">
              Kill switch, risk parameters, broker connection, and session
              controls
            </p>
          </div>
        </div>

        {/* Circuit breaker banner — only shown when not all-clear */}
        {cbData && !cbData.all_clear && (
          <CircuitBreakerSummary data={cbData} />
        )}

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Kill Switch — top left, most prominent */}
          <KillSwitchPanel
            data={killSwitchData}
            mutate={mutateAll}
          />

          {/* IB Gateway — top right */}
          <IBGatewayPanel data={gatewayData} config={configData} />

          {/* Risk Parameters — bottom left, full width on small */}
          <RiskParametersPanel data={configData} />

          {/* Session Controls + Notifications — bottom right */}
          <div className="space-y-4">
            <SessionControls mutateAll={mutateAll} />

            <NotificationsPanel />

            <NotificationTestPanel />

            {/* Circuit breaker status (always shown) */}
            <CircuitBreakerSummary data={cbData} />
          </div>
        </div>

        {/* WhatsApp alert status */}
        <WhatsAppStatusCard />

        {/* Trading Schedule — static reference */}
        <TradingScheduleCard />
      </main>
    </div>
  );
}
