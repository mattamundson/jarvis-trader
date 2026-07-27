// Settings API — kill switch, risk config, IB gateway controls
// All calls proxy through fetchEngine/postEngine in @/lib/api.ts
// NEVER hardcode an absolute engine URL or make fetch calls directly.

import { fetchEngine, postEngine } from "@/lib/api";
import type { ExecutionPathProbe } from "@/lib/executionPath";

// ── Kill Switch ───────────────────────────────────────────────────────────

export interface KillSwitchStatus {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  live_trading_enabled: boolean;
  require_human_approval: boolean;
  daily_pnl: number;
  equity_peak: number;
  current_equity: number;
  drawdown_pct: number;
  orders_last_minute: number;
}

export async function getKillSwitchStatus(): Promise<KillSwitchStatus> {
  return fetchEngine<KillSwitchStatus>("/safety/status");
}

export async function activateKillSwitch(
  reason: string
): Promise<{ status: string; reason: string }> {
  return postEngine<{ status: string; reason: string }>(
    `/safety/kill-switch/activate?reason=${encodeURIComponent(reason)}`
  );
}

export async function deactivateKillSwitch(): Promise<{ status: string }> {
  return postEngine<{ status: string }>("/safety/kill-switch/deactivate");
}

// ── Risk Config ───────────────────────────────────────────────────────────

export interface SafetyConfig {
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  max_position_size_pct: number;
  max_contracts_per_instrument: number;
  max_overnight_contracts: number;
  max_orders_per_minute: number;
  max_single_order_value: number;
  max_margin_utilization: number;
  live_trading_enabled: boolean;
  require_human_approval: boolean;
  ibkr_host: string;
  ibkr_port: number;
  ibkr_client_id: number;
  ibkr_paper_mode: boolean;
}

export async function getSafetyConfig(): Promise<SafetyConfig> {
  return fetchEngine<SafetyConfig>("/safety/config");
}

// ── IB Gateway ────────────────────────────────────────────────────────────

export interface IBGatewayStatus {
  status: string;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  paper_mode: boolean;
  live_trading: boolean;
  kill_switch_active: boolean;
  account_id?: string | null;
  last_sync?: string | null;
  uptime_seconds?: number;
  // D3-01: honest execution-path fields — see @/lib/executionPath.
  execution_connected_verified?: boolean | null;
  ib_execution_stale?: boolean | null;
  execution_path?: ExecutionPathProbe | null;
}

export async function getIBGatewayStatus(): Promise<IBGatewayStatus> {
  return fetchEngine<IBGatewayStatus>("/health");
}

// ── Circuit Breakers ──────────────────────────────────────────────────────

export interface CircuitBreakerFull {
  daily_pnl: number;
  daily_limit: number;
  daily_pnl_pct: number;
  daily_limit_pct: number;
  daily_limit_breached: boolean;
  drawdown_pct: number;
  drawdown_limit_pct: number;
  drawdown_breached: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  pnl_source: string;
  current_balance: number;
  starting_balance: number;
  orders_last_minute: number;
  all_clear: boolean;
}

export async function getCircuitBreakers(): Promise<CircuitBreakerFull> {
  return fetchEngine<CircuitBreakerFull>("/safety/circuit-breakers");
}

// ── Session Controls ──────────────────────────────────────────────────────

export async function resetDailyPnl(): Promise<{
  status: string;
  message: string;
}> {
  return postEngine<{ status: string; message: string }>(
    "/safety/reset-daily-pnl"
  );
}

// ── Simulate Trade ────────────────────────────────────────────────────────

export interface SimulateTradePayload {
  symbol: string;
  action: "LONG" | "SHORT";
  entry_price: number;
  stop_loss: number;
  quantity: number;
}

export interface SimulateTradeResult {
  status: string;
  trade_id?: string;
  message?: string;
  pnl_estimate?: number;
  risk_amount?: number;
  [key: string]: unknown;
}

export async function simulateTrade(
  payload: SimulateTradePayload
): Promise<SimulateTradeResult> {
  return postEngine<SimulateTradeResult>("/test/simulate-trade", payload);
}
