// All calls proxy through Next.js rewrites → http://localhost:8010
const ENGINE = "/api/engine";
const FETCH_TIMEOUT_MS = 30000; // 30 seconds
const RETRY_DELAY_MS = 2000; // 2 seconds

async function fetchWithTimeout<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Engine error ${res.status}: ${url}`);
    }

    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function fetchWithRetry<T>(
  url: string,
  options?: RequestInit,
  attempt: number = 1
): Promise<T> {
  try {
    return await fetchWithTimeout<T>(url, options);
  } catch (e) {
    const error = e instanceof Error ? e : new Error(String(e));

    // Only retry on network errors, not on HTTP errors
    const isNetworkError =
      error.message.includes("Failed to fetch") ||
      error.message.includes("AbortError") ||
      error.name === "AbortError";

    if (isNetworkError && attempt < 2) {
      // Single retry with 2s delay
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
      return fetchWithRetry<T>(url, options, attempt + 1);
    }

    throw error;
  }
}

export async function fetchEngine<T>(path: string, options?: RequestInit): Promise<T> {
  return fetchWithRetry<T>(`${ENGINE}${path}`, { cache: "no-store", ...options });
}

export async function postEngine<T>(path: string, body?: unknown): Promise<T> {
  return fetchWithRetry<T>(`${ENGINE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// API types (mirror engine Pydantic models)
export interface HealthResponse {
  status: string;
  version: string;
  live_trading: boolean;
  kill_switch_active: boolean;
  paper_mode: boolean;
  ibkr_connected: boolean;
  schwab_connected: boolean;
  uptime_seconds: number;
}

export interface SafetyStatus {
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
}

export interface TechnicalReport {
  symbol: string;
  timeframe: string;
  signal: number;
  confidence: number;
  trend: string;
  regime: string;
  indicators: Record<string, number>;
  support_levels: number[];
  resistance_levels: number[];
  reasoning: string;
  timestamp: string;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  type: string;
  last_price: number | null;
  change_pct: number | null;
}

export interface PriceSnapshotEntry {
  symbol: string;
  last_price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  yf_ticker: string;
  error?: string;
}

export type PriceSnapshot = Record<string, PriceSnapshotEntry>;

export interface MacroSnapshot {
  vix?: number | null;
  fed_funds_rate?: number | null;
  ten_year_yield?: number | null;
  unemployment?: number | null;
  timestamp?: string;
  [key: string]: unknown;
}

export interface SentimentData {
  symbol: string;
  score: number;
  post_count: number;
  source: string;
  timestamp: string;
}

export interface AgentDecision {
  id: number;
  created_at: string;
  agent_name: string;
  symbol: string;
  signal: number;
  confidence: number;
  reasoning: string;
  model_used: string;
  latency_ms: number;
}

export interface Position {
  symbol: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  is_futures: boolean;
}

export interface PortfolioSnapshot {
  total_equity: number;
  cash_balance: number;
  unrealized_pnl: number;
  realized_pnl: number;
  daily_pnl: number;
  margin_used: number;
  margin_available: number;
  positions: Position[];
}

export interface PaperPosition {
  trade_id: string;
  symbol: string;
  action: string;
  quantity: number;
  entry_price: number;
  entry_time: string;
  notes: string;
}

export interface PaperPerformance {
  total_pnl: number;
  win_rate: number;
  profit_factor: number;
  num_trades: number;
  max_dd: number;
  avg_win: number;
  avg_loss: number;
}

// ── History / persistence types (new SQLite endpoints) ────────────────────

export interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  realized_pnl: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  entry_time: string;
  exit_time: string | null;
  notes: string | null;
}

export interface DailyPnlRecord {
  date: string;
  realized_pnl: number;
  cumulative_pnl: number;
  num_trades: number;
}

export interface PerformanceSummary {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  gross_profit: number;
  gross_loss: number;
  net_pnl: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  sharpe_ratio: number | null;
  max_drawdown: number;
}

export interface DrawdownInfo {
  current_drawdown: number;
  max_drawdown: number;
  peak_equity: number;
  trough_equity: number;
  recovery_pct: number;
}

// ── Circuit breaker / IB Gateway types ───────────────────────────────────────

export interface CircuitBreakerState {
  /** Current daily P&L (negative = loss) */
  daily_pnl: number;
  /** Maximum allowed daily loss (negative number, e.g. -200) */
  daily_limit: number;
  /** Current drawdown as a decimal (e.g. 0.012 = 1.2%) */
  drawdown_pct: number;
  /** Maximum drawdown threshold as a decimal (e.g. 0.10 = 10%) */
  drawdown_limit: number;
  /** Whether the kill switch is currently active */
  kill_switch_active: boolean;
  /** True when no circuit breaker is tripped and trading may proceed */
  all_clear: boolean;
}

// ── WebSocket types ─────────────────────────────────────────────────────────

export interface WebSocketStatus {
  status: "ok" | "not_initialized";
  connections: number;
}

// ── Journal types ─────────────────────────────────────────────────────────────

export interface JournalEntry {
  id: number;
  trade_id: string | null;
  timestamp: string;
  note: string;
  tags: string[] | null;
  mood: "confident" | "uncertain" | "frustrated" | "neutral" | null;
  lesson: string | null;
}

export interface JournalNote {
  id: number;
  trade_id: string | null;
  note_type: "observation" | "lesson" | "alert";
  title: string;
  body: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

// ── WebSocket API ────────────────────────────────────────────────────────────

/**
 * Check WebSocket server status (connected client count).
 * Useful for monitoring WebSocket manager health.
 */
export async function getWebSocketStatus(): Promise<WebSocketStatus> {
  return fetchEngine<WebSocketStatus>("/ws/status");
}

// ── Order Entry types ──────────────────────────────────────────────────────

export interface OrderRequest {
  symbol: string;
  direction: "BUY" | "SELL";
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  limit_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
}

export interface OrderResponse {
  order_id: string;
  symbol: string;
  direction: string;
  quantity: number;
  order_type: string;
  status: string;
  timestamp: string;
}

export async function postOrder(order: OrderRequest): Promise<OrderResponse> {
  return postEngine<OrderResponse>("/orders/place", order);
}

// ── MGC Paper Trading types ───────────────────────────────────────────────────

export interface PendingSignal {
  date: string | null;
  symbol: string | null;
  direction: string | null;
  entry_price: number | null;
  stop_level: number | null;
  target_1: number | null;
  regime: string | null;
  status: string | null;
  confidence?: number | null;
}

export interface MGCPerformanceResponse {
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  net_pnl: number | null;
  max_drawdown: number | null;
  kill_switch_active: boolean;
  monthly_breakdown: Array<{
    month: string;
    trades: number;
    pnl: number;
    win_rate: number | null;
  }> | null;
}

export interface PaperTradePayload {
  entry_date: string;
  exit_date: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  contracts: number;
}

export interface MGCSignalResponse {
  direction: string | null;
  date: string;
  symbol: string;
  signal: string;
  regime: string | null;
  adaptive_stc_os: number;
  adaptive_stc_ob: number;
  entry_price: number | null;
  stop_level: number | null;
  target_1: number | null;
  target_2: number | null;
  atr: number | null;
  bias: string | null;
  stc_val: number | null;
  stc_signal: string | null;
  ema_trend: string | null;
  confidence: number | null;
  config: string | null;
  error?: string;
  bars_received?: number;
}

// ── Validation / Analytics types ─────────────────────────────────────────────

export interface ValidationMetrics {
  profit_factor: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  max_drawdown: number;
  total_trades: number;
  period_days: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
}

export interface ValidationReport {
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
  metrics: ValidationMetrics;
  recommendation: string;
}

export interface CompareToBacktestResponse {
  comparison: {
    profit_factor: { retention_pct: number };
    sharpe_ratio: { retention_pct: number };
    [key: string]: { retention_pct: number };
  };
}

// ── Kill Switch API ──────────────────────────────────────────────────────────

export interface KillSwitchStatus {
  active: boolean;
  reason: string | null;
  activated_at: string | null;
}

export async function fetchKillSwitchStatus(): Promise<KillSwitchStatus> {
  return fetchEngine<KillSwitchStatus>("/paper/kill-switch");
}

export async function toggleKillSwitch(
  action: "activate" | "deactivate",
  reason?: string
): Promise<KillSwitchStatus> {
  const params = new URLSearchParams({ action });
  if (reason) params.set("reason", reason);
  return postEngine<KillSwitchStatus>(`/paper/kill-switch?${params.toString()}`);
}

export async function resetPendingSignals(): Promise<{ cleared: number }> {
  return postEngine<{ cleared: number }>("/paper/reset-pending-signals");
}
