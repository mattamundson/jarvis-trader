import { fetchEngine, postEngine } from "@/lib/api";

export type TradeIntentDirection = "BUY" | "SELL";
export type TradeIntentOrderType = "MARKET" | "LIMIT";
export type TradeIntentStatus =
  | "PREVIEWED"
  | "SUBMITTING"
  | "SUBMITTED"
  | "BLOCKED"
  | "REJECTED"
  | "EXPIRED";

export interface TradeIntentPreviewRequest {
  idempotency_key: string;
  symbol: string;
  direction: TradeIntentDirection;
  order_type: TradeIntentOrderType;
  limit_price?: number;
  stop_loss: number;
  take_profit: number;
  max_risk_fraction: number;
  requested_quantity?: number;
  ttl_seconds?: number;
}

export interface TradeIntentPreview {
  symbol: string;
  direction: TradeIntentDirection;
  order_type: TradeIntentOrderType;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  account_equity: number;
  max_risk_fraction: number;
  max_trade_loss_usd: number;
  risk_budget_usd: number;
  contract_multiplier: number;
  risk_points_per_unit: number;
  reward_points_per_unit: number;
  dollar_risk_per_unit: number;
  requested_quantity: number | null;
  max_contracts: number;
  final_quantity: number;
  final_dollar_risk: number;
  reward_risk_ratio: number;
  can_submit: boolean;
  blocking_reason: string | null;
}

export interface TradeIntentResponse {
  intent_id: string;
  status: TradeIntentStatus;
  preview: TradeIntentPreview;
  broker_result?: Record<string, unknown> | null;
  order_id?: string | null;
  terminal_reason?: string | null;
}

export async function previewManualTradeIntent(
  payload: TradeIntentPreviewRequest,
): Promise<TradeIntentResponse> {
  return postEngine<TradeIntentResponse>("/trade-intents/preview", payload);
}

export async function fetchManualTradeIntent(intentId: string): Promise<TradeIntentResponse> {
  return fetchEngine<TradeIntentResponse>(`/trade-intents/${encodeURIComponent(intentId)}`);
}

export async function submitManualTradeIntent(intentId: string): Promise<TradeIntentResponse> {
  return postEngine<TradeIntentResponse>(`/trade-intents/${encodeURIComponent(intentId)}/submit`);
}

export function manualIntentCapability(
  intent: TradeIntentResponse | null | undefined,
  canApprovePaper: boolean,
): { canSubmit: boolean; requiresReconciliation: boolean; reasons: string[] } {
  const reasons: string[] = [];
  if (!intent) {
    return { canSubmit: false, requiresReconciliation: false, reasons: ["preview required"] };
  }

  const requiresReconciliation = intent.status === "SUBMITTING";
  if (!canApprovePaper) reasons.push("paper execution gate is not ready");
  if (intent.status !== "PREVIEWED") reasons.push(`intent status is ${intent.status}`);
  if (!intent.preview.can_submit) reasons.push(intent.preview.blocking_reason || "server risk policy blocked the intent");
  if (intent.preview.final_quantity < 1) reasons.push("server-sized quantity is zero");

  return {
    canSubmit: reasons.length === 0,
    requiresReconciliation,
    reasons,
  };
}

export function buildTradeIntentIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `manual-${crypto.randomUUID()}`;
  }
  // Fallback is only for runtimes without Web Crypto. The server additionally
  // enforces request-fingerprint uniqueness across active intents, so this key
  // is not the sole duplicate-order defense.
  return `manual-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
