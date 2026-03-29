// All calls proxy through Next.js rewrites → http://localhost:8010
const ENGINE = "/api/engine";

export async function fetchEngine<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${ENGINE}${path}`, { cache: "no-store", ...options });
  if (!res.ok) throw new Error(`Engine error ${res.status}: ${path}`);
  return res.json();
}

export async function postEngine<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${ENGINE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Engine error ${res.status}: ${path}`);
  return res.json();
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

// ── Analytics / Validation types ──────────────────────────────────────────────

/**
 * Mirrors engine PerformanceMetrics dataclass + get_validation_report() shape.
 * Returned by GET /analytics/performance
 */
export interface AnalyticsPerformanceMetrics {
  profit_factor: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  avg_win: number;
  avg_loss: number;
  max_drawdown: number;
  total_trades: number;
  total_pnl: number;
  period_days: number;
  meets_paper_threshold: boolean;
}

export interface ValidationReport {
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
  metrics: AnalyticsPerformanceMetrics;
  thresholds: {
    profit_factor: number;
    sharpe_ratio: number;
    min_trades_required: number;
  };
  recommendation: string;
}

export interface CompareToBacktestResponse {
  forward: AnalyticsPerformanceMetrics;
  backtest: {
    profit_factor: number;
    sharpe_ratio: number;
  };
  comparison: {
    profit_factor: {
      forward: number;
      backtest: number;
      diff: number;
      retention_pct: number;
    };
    sharpe_ratio: {
      forward: number;
      backtest: number;
      diff: number;
      retention_pct: number;
    };
    win_rate: {
      forward: number;
      backtest: null;
      note: string;
    };
  };
  degradation_ok: boolean;
}

export async function getValidationReport(): Promise<ValidationReport> {
  return fetchEngine<ValidationReport>("/analytics/performance");
}

export async function getCompareToBacktest(): Promise<CompareToBacktestResponse> {
  return fetchEngine<CompareToBacktestResponse>("/analytics/performance/compare");
}

// ── MGC Paper Trading types ───────────────────────────────────────────────────

export interface MGCSignalResponse {
  direction: string | null;
  entry_price: number | null;
  stop_level: number | null;
  target_1: number | null;
  regime: string | null;
  confidence: number | null;
  timestamp: string | null;
  [key: string]: unknown;
}

export interface PendingSignal {
  date: string | null;
  symbol: string | null;
  direction: string | null;
  entry_price: number | null;
  stop_level: number | null;
  target_1: number | null;
  regime: string | null;
  status: string | null;
  [key: string]: unknown;
}

export interface MonthlyBreakdown {
  month: string;
  trades: number;
  pnl: number;
  win_rate: number | null;
}

export interface MGCPerformanceResponse {
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  net_pnl: number | null;
  max_drawdown: number | null;
  kill_switch_active: boolean;
  monthly_breakdown: MonthlyBreakdown[] | null;
  [key: string]: unknown;
}

export interface PaperTradePayload {
  entry_date: string;
  exit_date: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  contracts: number;
}

export async function fetchMGCSignal(): Promise<MGCSignalResponse> {
  return fetchEngine<MGCSignalResponse>("/paper/mgc-signal");
}

export async function fetchPendingSignals(): Promise<PendingSignal[]> {
  return fetchEngine<PendingSignal[]>("/paper/pending-signals");
}

export async function fetchMGCPerformance(): Promise<MGCPerformanceResponse> {
  return fetchEngine<MGCPerformanceResponse>("/paper/mgc-performance");
}

export async function logPaperTrade(data: PaperTradePayload): Promise<unknown> {
  return postEngine("/paper/mgc-log-trade", data);
}

// ── IB Gateway types ─────────────────────────────────────────────────────────

export interface IBGatewayStatusInfo {
  /** Overall engine health status string (e.g. "healthy", "degraded") */
  status: string;
  /** True when IB Gateway is connected */
  ibkr_connected: boolean;
  /** True when running in paper mode */
  paper_mode: boolean;
  /** True when live trading is enabled */
  live_trading: boolean;
  /** Kill switch state */
  kill_switch_active: boolean;
  /** Account identifier if returned by the engine */
  account_id?: string | null;
  /** ISO timestamp of most recent successful engine response */
  last_sync?: string | null;
  /** Seconds since the engine started */
  uptime_seconds?: number;
  /** Engine version string */
  version?: string;
}
