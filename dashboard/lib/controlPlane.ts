import { fetchEngine } from "@/lib/api";

export interface ControlPlaneHealth {
  status: string;
  live_trading: boolean;
  paper_mode: boolean;
  kill_switch_active: boolean;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
}

export interface ControlPlaneSafety {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  live_trading_enabled: boolean;
  require_human_approval: boolean;
  daily_pnl: number;
  max_daily_loss: number;
  portfolio_equity: number;
  peak_equity: number;
  current_drawdown: number;
  orders_today: number;
  drawdown_pct?: number;
  drawdown_limit_pct?: number;
  drawdown_breached?: boolean;
}

export interface ControlPlanePosition {
  symbol: string;
  quantity: number;
  avg_cost?: number | null;
  average_price?: number | null;
  current_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  unrealized_pnl_pct?: number | null;
  is_futures?: boolean;
  is_live?: boolean;
  source?: string | null;
  as_of?: string | number | null;
  stale_after_s?: number | null;
}

export interface ControlPlanePortfolio {
  total_equity: number;
  cash_balance?: number;
  cash?: number;
  unrealized_pnl: number;
  realized_pnl: number;
  daily_pnl: number;
  margin_used: number;
  margin_available: number;
  positions: ControlPlanePosition[];
}

export interface ControlPlaneApproval {
  id: number;
  created_at: string;
  symbol: string;
  direction: string;
  confidence?: number | null;
  expires_at: string;
  status: string;
  stark_signal?: string | null;
  validation_only?: boolean;
  verdict?: Record<string, unknown> | null;
}

export interface PendingApprovalsResponse {
  count: number;
  candidates: ControlPlaneApproval[];
}

export interface ControlPlaneSnapshot {
  fetchedAt: string;
  health: ControlPlaneHealth | null;
  safety: ControlPlaneSafety | null;
  portfolio: ControlPlanePortfolio | null;
  portfolioRisk: Record<string, unknown> | null;
  pendingApprovals: PendingApprovalsResponse | null;
  paperStatus: Record<string, unknown> | null;
  errors: Record<string, string>;
}

async function capture<T>(
  key: string,
  promise: Promise<T>,
  errors: Record<string, string>,
): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    errors[key] = error instanceof Error ? error.message : String(error);
    return null;
  }
}

/**
 * Build one read-only operator snapshot from existing engine APIs.
 *
 * No broker credentials or mutation endpoints are used here. Each subsystem is
 * captured independently so one degraded endpoint does not hide the rest of the
 * cockpit; the UI must display those errors rather than infer a healthy state.
 */
export async function fetchControlPlaneSnapshot(): Promise<ControlPlaneSnapshot> {
  const errors: Record<string, string> = {};

  const [health, safety, portfolio, portfolioRisk, pendingApprovals, paperStatus] =
    await Promise.all([
      capture("health", fetchEngine<ControlPlaneHealth>("/health"), errors),
      capture("safety", fetchEngine<ControlPlaneSafety>("/safety/status"), errors),
      capture("portfolio", fetchEngine<ControlPlanePortfolio>("/portfolio"), errors),
      capture("portfolioRisk", fetchEngine<Record<string, unknown>>("/portfolio/risk"), errors),
      capture(
        "pendingApprovals",
        fetchEngine<PendingApprovalsResponse>("/approvals/pending"),
        errors,
      ),
      capture("paperStatus", fetchEngine<Record<string, unknown>>("/backtest/paper-status"), errors),
    ]);

  return {
    fetchedAt: new Date().toISOString(),
    health,
    safety,
    portfolio,
    portfolioRisk,
    pendingApprovals,
    paperStatus,
    errors,
  };
}

export function executionCapability(snapshot: ControlPlaneSnapshot): {
  mode: "PAPER" | "LIVE" | "UNKNOWN";
  canApprovePaper: boolean;
  reasons: string[];
} {
  const reasons: string[] = [];
  const health = snapshot.health;
  const safety = snapshot.safety;

  const mode = health?.live_trading || safety?.live_trading_enabled
    ? "LIVE"
    : health?.paper_mode === true || safety?.live_trading_enabled === false
      ? "PAPER"
      : "UNKNOWN";

  if (!health) reasons.push("health unavailable");
  if (!safety) reasons.push("safety state unavailable");
  if (mode !== "PAPER") reasons.push(`execution mode is ${mode}`);
  if (health && !health.ibkr_connected && !health.ibkr_execution_connected) {
    reasons.push("IBKR execution connection unavailable");
  }
  if (health?.kill_switch_active || safety?.kill_switch_active) {
    reasons.push("kill switch active");
  }
  if (safety?.drawdown_breached) reasons.push("drawdown limit breached");
  if (Object.keys(snapshot.errors).length > 0) reasons.push("cockpit state is degraded");

  return {
    mode,
    canApprovePaper: reasons.length === 0,
    reasons,
  };
}
