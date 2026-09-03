import { fetchEngine, postEngine } from "@/lib/api";

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

export interface CandidateTradeTerms {
  side: "LONG" | "SHORT" | null;
  entryPrice: number | null;
  stopPrice: number | null;
  targetPrice: number | null;
  quantity: number | null;
  riskPointsPerUnit: number | null;
  rewardPointsPerUnit: number | null;
  rewardRisk: number | null;
}

export interface CandidateApprovalCapability {
  canApprove: boolean;
  reasons: string[];
  terms: CandidateTradeTerms;
}

export interface ApprovalMutationResult {
  status: string;
  candidate_id: number;
  symbol?: string;
  direction?: string;
  entry_price?: number;
  order_id?: string;
  order_result?: Record<string, unknown>;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function finiteNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const numeric = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function positiveInteger(...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = finiteNumber(value);
    if (numeric !== null && Number.isInteger(numeric) && numeric > 0) return numeric;
  }
  return null;
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

export function killSwitchState(
  snapshot: ControlPlaneSnapshot | null | undefined,
): "ACTIVE" | "CLEAR" | "UNKNOWN" {
  const healthState = snapshot?.health?.kill_switch_active;
  const safetyState = snapshot?.safety?.kill_switch_active;

  if (healthState === true || safetyState === true) return "ACTIVE";
  if (healthState === false && safetyState === false) return "CLEAR";
  return "UNKNOWN";
}


export function executionCapability(snapshot: ControlPlaneSnapshot): {
  mode: "PAPER" | "LIVE" | "UNKNOWN";
  canApprovePaper: boolean;
  reasons: string[];
} {
  const reasons: string[] = [];
  const health = snapshot.health;
  const safety = snapshot.safety;

  const liveEvidence =
    health?.live_trading === true || safety?.live_trading_enabled === true;
  const paperEvidence =
    health?.paper_mode === true &&
    health?.live_trading === false &&
    safety?.live_trading_enabled === false;
  const mode = liveEvidence ? "LIVE" : paperEvidence ? "PAPER" : "UNKNOWN";

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

/**
 * Resolve the exact frozen candidate terms the existing approval_queue_router
 * will use when the browser sends an empty approve body.
 *
 * Deliberately mirrors server precedence rather than inventing client-side
 * overrides. Final broker authorization and sizing remain server-side.
 */
export function candidateTradeTerms(candidate: ControlPlaneApproval): CandidateTradeTerms {
  const verdict = record(candidate.verdict);
  const tradeDecision = record(verdict.trade_decision);
  const fundDecision = record(verdict.fund_decision);
  const direction = String(candidate.direction || "").toUpperCase();
  const side = direction === "LONG" || direction === "SHORT" ? direction : null;

  // Mirrors approval_queue_router: limit_price -> entry_price -> stop_price.
  const entryPrice = finiteNumber(
    tradeDecision.limit_price,
    tradeDecision.entry_price,
    tradeDecision.stop_price,
  );
  const stopPrice = finiteNumber(tradeDecision.stop_price, tradeDecision.stop_loss);
  const targetPrice = finiteNumber(
    tradeDecision.target_1,
    tradeDecision.target_price,
    tradeDecision.take_profit,
  );
  const quantity = positiveInteger(fundDecision.final_quantity, tradeDecision.quantity);

  let riskPointsPerUnit: number | null = null;
  let rewardPointsPerUnit: number | null = null;
  let rewardRisk: number | null = null;
  if (entryPrice !== null && stopPrice !== null && targetPrice !== null && side !== null) {
    riskPointsPerUnit = Math.abs(entryPrice - stopPrice);
    rewardPointsPerUnit = Math.abs(targetPrice - entryPrice);
    if (riskPointsPerUnit > 0) rewardRisk = rewardPointsPerUnit / riskPointsPerUnit;
  }

  return {
    side,
    entryPrice,
    stopPrice,
    targetPrice,
    quantity,
    riskPointsPerUnit,
    rewardPointsPerUnit,
    rewardRisk,
  };
}

export function candidateApprovalCapability(
  snapshot: ControlPlaneSnapshot,
  candidate: ControlPlaneApproval,
  nowMs: number = Date.now(),
): CandidateApprovalCapability {
  const global = executionCapability(snapshot);
  const terms = candidateTradeTerms(candidate);
  const reasons = [...global.reasons];

  if (candidate.status !== "pending") reasons.push(`candidate status is ${candidate.status}`);
  if (candidate.validation_only) reasons.push("strategy is validation-only");
  if (terms.side === null) reasons.push("candidate direction is not LONG/SHORT");
  if (terms.entryPrice === null) reasons.push("entry price unavailable");
  if (terms.stopPrice === null) reasons.push("protective stop unavailable");
  if (terms.targetPrice === null) reasons.push("target unavailable");
  if (terms.quantity === null) reasons.push("quantity unavailable");

  const expiryMs = Date.parse(candidate.expires_at);
  if (!Number.isFinite(expiryMs)) reasons.push("candidate expiry is invalid");
  else if (expiryMs <= nowMs) reasons.push("candidate expired");

  if (
    terms.side === "LONG" &&
    terms.entryPrice !== null &&
    terms.stopPrice !== null &&
    terms.stopPrice >= terms.entryPrice
  ) {
    reasons.push("LONG stop must be below entry");
  }
  if (
    terms.side === "SHORT" &&
    terms.entryPrice !== null &&
    terms.stopPrice !== null &&
    terms.stopPrice <= terms.entryPrice
  ) {
    reasons.push("SHORT stop must be above entry");
  }
  if (
    terms.side === "LONG" &&
    terms.entryPrice !== null &&
    terms.targetPrice !== null &&
    terms.targetPrice <= terms.entryPrice
  ) {
    reasons.push("LONG target must be above entry");
  }
  if (
    terms.side === "SHORT" &&
    terms.entryPrice !== null &&
    terms.targetPrice !== null &&
    terms.targetPrice >= terms.entryPrice
  ) {
    reasons.push("SHORT target must be below entry");
  }

  return {
    canApprove: reasons.length === 0,
    reasons: [...new Set(reasons)],
    terms,
  };
}

/** Approve the frozen pipeline candidate through the existing paper-only server path. */
export async function approvePaperCandidate(candidateId: number): Promise<ApprovalMutationResult> {
  return postEngine<ApprovalMutationResult>(`/approvals/${candidateId}/approve`, {});
}

/** Reject a pending candidate through the existing audited approval queue. */
export async function rejectPaperCandidate(
  candidateId: number,
  reason?: string,
): Promise<ApprovalMutationResult> {
  return postEngine<ApprovalMutationResult>(`/approvals/${candidateId}/reject`, { reason });
}
