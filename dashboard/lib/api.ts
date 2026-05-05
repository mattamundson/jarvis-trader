// All dashboard calls MUST use fetchEngine() or postEngine() below.
// These functions proxy through Next.js rewrites to the engine backend.
// NEVER hardcode an absolute engine URL or make fetch calls directly.
const ENGINE = "/api/engine";
const FETCH_TIMEOUT_MS = 30000; // 30 seconds
const RETRY_DELAY_MS = 2000; // 2 seconds

// API key injected via NEXT_PUBLIC_ENGINE_API_KEY (set in dashboard/.env.local).
// Run `python scripts/rotate_dev_api_key.py` from repo root to sync with engine/.env API_KEY.
// Fallback matches engine/.env.example only — rotate before any network exposure.
const API_KEY =
  process.env.NEXT_PUBLIC_ENGINE_API_KEY ?? "jarvis-dev-key-change-me";

function engineHeaders(extra?: HeadersInit): HeadersInit {
  return {
    "X-API-Key": API_KEY,
    ...extra,
  };
}

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

export async function fetchEngine<T = any>(path: string, options?: RequestInit): Promise<T> {
  return fetchWithRetry<T>(`${ENGINE}${path}`, {
    cache: "no-store",
    ...options,
    headers: engineHeaders(options?.headers),
  });
}

export async function postEngine<T = any>(path: string, body?: unknown): Promise<T> {
  return fetchWithRetry<T>(`${ENGINE}${path}`, {
    method: "POST",
    headers: engineHeaders({ "Content-Type": "application/json" }),
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * Fetch a binary/non-JSON response from the engine (e.g. CSV downloads).
 * Returns the raw Response so the caller can call .blob(), .text(), etc.
 */
export async function fetchEngineRaw(path: string, options?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${ENGINE}${path}`, {
      cache: "no-store",
      ...options,
      signal: controller.signal,
      headers: engineHeaders(options?.headers),
    });
    return res;
  } finally {
    clearTimeout(timeoutId);
  }
}

// API types (mirror engine Pydantic models)
export interface HealthResponse {
  status: string;
  version: string;
  live_trading: boolean;
  kill_switch_active: boolean;
  paper_mode: boolean;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
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

export const JARVIS_QUICK_ANALYSIS_PERIODS = ["5d", "1mo", "3mo", "6mo"] as const;

export type JarvisQuickAnalysisPeriod = (typeof JARVIS_QUICK_ANALYSIS_PERIODS)[number];

export interface JarvisQuickAnalysisRequest {
  symbol: string;
  period?: JarvisQuickAnalysisPeriod;
}

export interface JarvisQuickAnalysisResponse {
  symbol: string;
  period: string;
  analysis: string;
  model: string;
  generated_at: string;
}

export function normalizeJarvisSymbolInput(symbol: string): string {
  return symbol.trim().toUpperCase();
}

export async function analyzeJarvisSymbol(
  body: JarvisQuickAnalysisRequest
): Promise<JarvisQuickAnalysisResponse> {
  return postEngine<JarvisQuickAnalysisResponse>("/jarvis/analyze", {
    symbol: normalizeJarvisSymbolInput(body.symbol),
    period: body.period,
  });
}

/** OHLCV bar for charts (`time` = unix seconds; engine may send ISO strings — normalize in hooks). */
export interface OHLCVBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  vwap?: number;
  stc?: number;
  ema_8?: number;
  ema_21?: number;
  ema_34?: number;
}

/** POST /analyze/technical — engine nested payload plus optional flattened fields for chart overlays. */
export interface TechnicalAnalysisResult {
  symbol?: string;
  timestamp?: string;
  timeframe?: string;
  signal?: string | number;
  confidence?: number;
  trend?: string | null;
  regime?: string | null;
  is_overbought?: boolean;
  is_oversold?: boolean;
  summary?: string | null;
  reasoning?: string | null;
  scores?: Record<string, number>;
  levels?: Record<string, unknown>;
  raw_indicators?: Record<string, unknown>;
  ema_8?: number;
  ema_21?: number;
  ema_34?: number;
  kelt_inner_upper?: number;
  kelt_inner_lower?: number;
  entry_price?: number;
  stop_level?: number;
  target_1?: number;
  stc_val?: number;
  stc_signal?: string;
  direction?: string;
  adaptive_stc_ob?: number | null;
  adaptive_stc_os?: number | null;
  atr?: number;
  ema_trend?: string;
}

/** GET /backtest/regime-status */
export interface RegimeStatusResult {
  current_regime?: string;
  regime_breakdown?: Record<string, number>;
  adaptive_stc_os?: number | null;
  adaptive_stc_ob?: number | null;
  [key: string]: unknown;
}

/** GET /watchlist/scan */
export interface WatchlistScanRow {
  symbol: string;
  signal?: string;
  direction?: string;
  entry_price?: number;
  stop_level?: number;
  target_1?: number;
}

export interface WatchlistScanResponse {
  symbols?: WatchlistScanRow[];
  signals?: unknown[];
}

/** GET /pipeline/history */
export interface PipelineHistoryEntry {
  id?: string | number;
  created_at?: string;
  timestamp?: string;
  symbol?: string;
  agent_name?: string;
  final_action?: string;
  confidence?: number;
  regime?: string;
  risk_verdict?: string | null;
}

/** GET /options/chain/{symbol} */
export interface OptionsContract {
  strike: number;
  delta?: number;
  bid?: number;
  ask?: number;
  iv?: number | null;
  open_interest?: number | string;
}

export interface OptionsChainData {
  error?: string;
  underlying_price: number;
  expiry: string;
  iv_rank?: number | null;
  calls: OptionsContract[];
  puts: OptionsContract[];
}

/** GET /options/greeks */
export interface OptionsGreeksPortfolio {
  error?: string;
  total_delta?: number;
  total_gamma?: number;
  total_theta?: number;
  total_vega?: number;
  positions_count?: number | string;
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
  created_at?: string;
  timestamp?: string;
  agent_name?: string;
  source?: string;
  symbol: string;
  signal?: number;
  action?: string;
  confidence: number;
  reasoning?: string;
  summary?: string;
  model_used?: string;
  latency_ms?: number;
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

/** GET /discord/intelligence — Discord signal status for dashboard widget */
export interface DiscordIntelligenceStatus {
  symbols: Record<
    string,
    {
      discord_signal_active: number;
      discord_win_rate_context: number;
      discord_proximity_entry: number;
      discord_proximity_target: number;
      discord_alignment: number;
    }
  >;
  last_updated: string;
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

/** Raw SQLite `daily_pnl` row — may use `total_trades` and omit `cumulative_pnl`. */
export type DailyPnlRow = Partial<DailyPnlRecord> & {
  date: string;
  realized_pnl?: number;
  total_trades?: number;
};

/**
 * Normalize engine daily_pnl rows for dashboard widgets (running cumulative when missing).
 */
export function normalizeDailyPnlRows(rows: DailyPnlRow[]): DailyPnlRecord[] {
  let cum = 0;
  return rows.map((r) => {
    const realized = Number(r.realized_pnl ?? 0);
    cum += realized;
    const num =
      typeof r.num_trades === "number"
        ? r.num_trades
        : typeof r.total_trades === "number"
          ? r.total_trades
          : 0;
    return {
      date: String(r.date).slice(0, 10),
      realized_pnl: realized,
      cumulative_pnl: typeof r.cumulative_pnl === "number" ? r.cumulative_pnl : cum,
      num_trades: num,
    };
  });
}

/** GET /portfolio/history/daily-pnl */
export interface DailyPnLHistoryResponse {
  daily_pnl: DailyPnlRecord[];
  days: number;
  count: number;
}

export async function fetchDailyPnLHistory(options?: {
  days?: number;
}): Promise<DailyPnLHistoryResponse> {
  const q = new URLSearchParams();
  if (options?.days != null) q.set("days", String(options.days));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return fetchEngine<DailyPnLHistoryResponse>(`/portfolio/history/daily-pnl${suffix}`);
}

/** Fetch daily PnL history and normalize rows for charts / tables. */
export async function fetchDailyPnlHistoryNormalized(options?: {
  days?: number;
}): Promise<DailyPnlRecord[]> {
  const res = await fetchDailyPnLHistory(options);
  return normalizeDailyPnlRows((res.daily_pnl ?? []) as DailyPnlRow[]);
}

/** GET /portfolio/risk — correlation-aware sizing snapshot */
export interface PortfolioRiskResponse {
  instruments: string[];
  correlation_matrix: Record<string, number>;
  correlation_threshold: number;
  active_positions: Record<string, number>;
  open_symbol_count: number;
  correlation_reduction_active: boolean;
  default_max_contracts: number;
  correlated_max_contracts: number;
  total_margin_utilization: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  account_value: number;
}

export async function fetchPortfolioRisk(): Promise<PortfolioRiskResponse> {
  return fetchEngine<PortfolioRiskResponse>("/portfolio/risk");
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

export interface ClosedTrade {
  trade_id: string;
  symbol: string;
  direction: string; // LONG or SHORT
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  pnl: number;
  duration_seconds: number;
}

export interface ClosedPaperTradesResponse {
  status: string;
  trades: ClosedTrade[];
}

/** Canonical: GET /paper/validation/trades/closed */
export async function fetchClosedPaperTrades(): Promise<ClosedPaperTradesResponse> {
  return fetchEngine<ClosedPaperTradesResponse>("/paper/validation/trades/closed");
}

// ── Approval / Trade Gating API ──────────────────────────────────────────────

export interface PendingApproval {
  id: number;
  approval_id: string;
  symbol: string;
  action: "buy" | "sell" | "BUY" | "SELL";
  quantity: number;
  entry_price: number | null;
  status: "pending" | "approved" | "rejected" | "error";
  pipeline_snapshot: Record<string, unknown> | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  rejection_reason: string | null;
  paper_trade_id: string | null;
  ib_order_id: string | null;
  regime?: string;
  structure_position?: string;
  bias?: string;
  composite_score?: number | null;
  stc_contrib?: boolean | null;
  orb_contrib?: boolean | null;
  vwap_contrib?: boolean | null;
  risk_pct_used?: number | null;
}

export interface PendingApprovalRow {
  approval_id: string;
  symbol: string;
  action: "BUY" | "SELL" | "buy" | "sell";
  quantity: number;
  entry_price: number | null;
  created_at: string;
  pipeline_snapshot: Record<string, unknown> | null;
  status: "pending" | "approved" | "rejected" | "error";
}

export interface PendingApprovalsResponse {
  pending: PendingApproval[];
  count: number;
}

export interface ApprovalActionResult {
  status: "approved" | "rejected";
  approval_id: string;
  symbol: string;
  action: string;
  quantity: number;
  entry_price?: number;
  paper_trade_id?: string;
  reason?: string;
}

export async function getPendingApprovals(limit: number = 50): Promise<PendingApprovalsResponse> {
  return fetchEngine<PendingApprovalsResponse>(`/pipeline/pending-approvals?limit=${limit}`);
}

export async function postApprovePending(
  approvalId: string,
  body?: { entry_price?: number }
): Promise<ApprovalActionResult> {
  return postEngine<ApprovalActionResult>(`/pipeline/pending-approvals/${approvalId}/approve`, body || {});
}

export async function postRejectPending(
  approvalId: string,
  reason?: string
): Promise<ApprovalActionResult> {
  return postEngine<ApprovalActionResult>(`/pipeline/pending-approvals/${approvalId}/reject`, { reason: reason || "rejected_by_trader" });
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

// ── Super-Engine Status API ──────────────────────────────────────────────────

export interface SuperEngineComponentStatus {
  active: boolean;
  type?: string;
  last_check?: string;
}

export interface SuperEngineStatusResponse {
  polymarket: SuperEngineComponentStatus;
  openbb: SuperEngineComponentStatus;
  regime_guard: SuperEngineComponentStatus;
  sentiment_bridge: SuperEngineComponentStatus;
  model_drawer: SuperEngineComponentStatus;
  arb_scout: SuperEngineComponentStatus;
}

export async function fetchSuperEngineStatus(): Promise<SuperEngineStatusResponse> {
  return fetchEngine<SuperEngineStatusResponse>("/super-engine/status");
}

export async function resetPendingSignals(): Promise<{ cleared: number }> {
  return postEngine<{ cleared: number }>("/paper/reset-pending-signals");
}

// ── Analytics Endpoints ─────────────────────────────────────────────────────

export interface PerformanceMetricsResponse {
  sharpe_ratio: number;
  profit_factor: number;
  win_rate: number;
  max_drawdown: number;
  total_pnl: number;
  total_trades: number;
  expectancy: number;
  timestamp: string;
}

export interface TradeAnalyticsResponse {
  sharpe_ratio: number;
  profit_factor: number;
  max_drawdown_pct: number;
  win_rate: number;
  expectancy: number;
  total_trades: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  best_trade: number;
  worst_trade: number;
}

export interface SignalMetricsResponse {
  total_signals: number;
  profitable_signals: number;
  accuracy: number;
  avg_signal_to_entry_minutes: number;
  avg_entry_to_peak_minutes: number;
  avg_pnl_per_signal: number;
  best_time_of_day: string;
  worst_time_of_day: string;
}

export interface SignalQualityResponse {
  overall: SignalMetricsResponse;
  by_symbol: Record<string, SignalMetricsResponse>;
  by_regime: Record<string, SignalMetricsResponse>;
  recommendations: string[];
}

export interface TradesByDayItem {
  date: string;
  trades: number;
  pnl: number;
  win_rate: number;
}

export interface TradesBySymbolItem {
  symbol: string;
  trades: number;
  pnl: number;
  win_rate: number;
  avg_pnl: number;
}

export interface TradesByHourItem {
  hour: number;
  trades: number;
  pnl: number;
  win_rate: number;
}

// ── Pipeline Profiling Endpoints ────────────────────────────────────────────

export interface ProfilingReport {
  [key: string]: unknown;
}

export interface ProfilingSummaryResponse {
  status: string;
  current_run: ProfilingReport;
}

export interface ProfilingAverageItem {
  stage: string;
  avg_ms: number;
  min_ms: number;
  max_ms: number;
}

export interface ProfilingAveragesResponse {
  status: string;
  rolling_averages: ProfilingAverageItem[];
  period: string;
}

export interface ProfilingHistoryResponse {
  status: string;
  history: ProfilingReport[];
  retrieved_count: number;
  total_stored: number;
  max_capacity: number;
}

export interface ProfilingStatsResponse {
  status: string;
  profiler_enabled: boolean;
  max_history: number;
  stored_runs: number;
  utilization_pct: number;
  current_run: ProfilingReport;
  stage_averages: ProfilingAverageItem[];
}

// ── Validation Endpoints ────────────────────────────────────────────────────

export interface ValidationGate {
  name: string;
  current: number;
  target: number;
  passes: boolean;
  unit: string;
}

export interface ValidationGatesData {
  gates: ValidationGate[];
  days_elapsed: number;
  days_remaining: number;
  overall_pass: boolean;
}

export interface ValidationAlert {
  timestamp?: string;
  gate?: string;
  status?: string;
  message?: string;
  [key: string]: unknown;
}

export interface ValidationAlertsResponse {
  alerts: ValidationAlert[];
  current_gates: Record<string, string>;
  status: string;
  message?: string;
  error?: string;
}

export interface ValidationReadinessCriterion {
  name: string;
  target: string;
  description: string;
}

export interface ValidationReadinessResponse {
  criteria: ValidationReadinessCriterion[];
  description: string;
  phase: string;
}

// ── System Endpoints ────────────────────────────────────────────────────────

export interface BackupFile {
  filename: string;
  size_bytes: number;
  created_at: string;
  [key: string]: unknown;
}

export interface BackupStatusResponse {
  success: boolean;
  timestamp: string;
  backup_status: {
    last_backup_time?: string;
    last_backup_size_bytes?: number;
    backup_count?: number;
    retention_days?: number;
    available_backups?: BackupFile[];
    [key: string]: unknown;
  };
}

export interface Phase3ReadinessResponse {
  status: string;
  ready: boolean;
  requirements: Record<string, unknown>;
  timestamp: string;
}

// ── Rolling WFE Monitoring ─────────────────────────────────────────────────

export interface WFEInstrument {
  symbol: string;
  current_wfe: number | null;
  kill_threshold: number;
  status: "healthy" | "warning" | "critical" | "insufficient_data";
  trades_in_window: number;
  window_days: number;
  current_pf: number | null;
}

export interface WFEResponse {
  instruments: WFEInstrument[];
  as_of: string;
}

export async function fetchRollingWFE(): Promise<WFEResponse> {
  return fetchEngine<WFEResponse>("/paper/validation/wfe");
}

// ── Trade Journal (US-1404) ────────────────────────────────────────────────

export interface TradeJournalEntry {
  id: number;
  trade_id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  pnl: number | null;
  status: string;
  strategy_params: string | null;
  notes: string | null;
  // Signal provenance
  regime: string | null;
  structure_position: string | null;
  bias: string | null;
  composite_score: number | null;
  stc_contrib: number | null;
  orb_contrib: number | null;
  vwap_contrib: number | null;
  // Trade attribution (US-2130)
  regime_tier: number | null;
  deciding_stage: string | null;
  bull_score: number | null;
  bear_score: number | null;
  debate_confidence: number | null;
}

export async function fetchTradeJournal(
  symbol?: string,
  regime?: string,
  limit?: number
): Promise<TradeJournalEntry[]> {
  const params = new URLSearchParams();
  if (symbol) params.append("symbol", symbol);
  if (regime) params.append("regime", regime);
  if (limit) params.append("limit", String(limit));

  const queryString = params.toString();
  const path = queryString ? `/trades/journal?${queryString}` : "/trades/journal";
  return fetchEngine<TradeJournalEntry[]>(path);
}

// ── EOD Summary (US-1504) ────────────────────────────────────────────────────

export interface ValidationGatesSummary {
  pf: number | null;
  sharpe: number | null;
  win_rate: number | null;
  trades_count: number;
  days_trading: number;
  max_drawdown: number | null;
}

export interface EODSummary {
  date: string;
  trades_today: number;
  pnl_today_usd: number;
  wins_today: number;
  losses_today: number;
  win_rate_today: number | null;
  avg_r_today: number | null;
  cumulative_trades: number;
  cumulative_pnl_usd: number;
  validation_gates: ValidationGatesSummary;
  status: "on_track" | "at_risk" | "insufficient_data";
}

export async function fetchEODSummary(): Promise<EODSummary> {
  return fetchEngine<EODSummary>("/paper/validation/summary/eod");
}

// ── Approved paper gates (MCL / MNQ) — Phase 4 dashboard ─────────────────────

export interface ApprovedPaperValidationGate {
  name: string;
  current: number;
  target: number;
  passes: boolean;
  unit: string;
}

export interface ApprovedInstrumentGateRow {
  symbol: string;
  trade_count: number;
  days_with_trades: number;
  gates: ApprovedPaperValidationGate[];
  overall_pass: boolean;
}

export interface ApprovedPaperGatesResponse {
  status: string;
  thresholds: Record<string, number>;
  instruments: ApprovedInstrumentGateRow[];
  note: string;
}

export async function fetchApprovedPaperGates(): Promise<ApprovedPaperGatesResponse> {
  return fetchEngine<ApprovedPaperGatesResponse>(
    "/paper/validation/approved-paper-gates"
  );
}

// ── Streak Tracker (Sprint 14) ───────────────────────────────────────────────

export interface StreakRecord {
  type: "WIN" | "LOSS";
  count: number;
  start_date: string;
  end_date: string;
}

export interface StreaksResponse {
  current_streak: { type: "WIN" | "LOSS" | "NONE"; count: number };
  max_win_streak: number;
  max_loss_streak: number;
  streak_history: StreakRecord[];
}

// ── Validation Checkpoint (US-2403) ─────────────────────────────────────────

export interface GateResult {
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
  current_value: number | null;
  target_value: number;
}

export interface ValidationCheckpointResponse {
  overall_status: string;
  trade_count: number;
  trading_days: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  gates: Record<string, GateResult>;
  validation_start: string | null;
  days_elapsed: number;
  days_remaining: number;
}

export async function fetchValidationCheckpoint(): Promise<ValidationCheckpointResponse> {
  return fetchEngine<ValidationCheckpointResponse>("/paper/validation/checkpoint");
}

export interface JarvisEvent {
  id: string;
  type: string;
  symbol: string | null;
  message: string;
  severity: "info" | "warn" | "critical";
  timestamp: string;
}

export interface EventsResponse {
  events: JarvisEvent[];
  count: number;
  buffer_size: number;
}

export async function fetchEvents(limit: number = 20): Promise<EventsResponse> {
  return fetchEngine<EventsResponse>(`/events/recent?limit=${limit}`);
}

// ── Dual-TF Confirmation (Sprint 24) ─────────────────────────────────────────

export interface DualTFTimeframe {
  stc_val: number;
  direction: "long" | "short" | "neutral";
}

export interface DualTFSymbol {
  symbol: string;
  confirmed: boolean;
  direction: "long" | "short" | "neutral";
  stc_os: number;
  stc_ob: number;
  tf_1h: DualTFTimeframe | null;
  tf_15m: DualTFTimeframe | null;
  error?: string;
}

export interface DualTFResponse {
  timestamp: string;
  symbols: DualTFSymbol[];
}

// ── Regime Attribution (Sprint 24) ───────────────────────────────────────────

export interface RegimeStatRow {
  regime: string;
  trade_count: number;
  win_rate_pct: number;
  total_pnl: number;
}

export interface RegimeStatsResponse {
  regimes: RegimeStatRow[];
  total_closed_trades: number;
}

// ── Unrealized P&L Widget ────────────────────────────────────────────────────

export interface UnrealizedPosition {
  trade_id: string;
  symbol: string;
  direction: string;
  quantity: number;
  entry_price: number;
  current_price: number | null;
  unrealized_pnl: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  stop_distance: number | null;
  target_distance: number | null;
}

export type UnrealizedPositionsResponse = UnrealizedPosition[];

// ── Win Rate by Hour Widget ──────────────────────────────────────────────────

export interface HourlyStatItem {
  hour: number;
  label: string;
  win_rate: number;
  trades: number;
}

export interface HourlyStatsResponse {
  hourly_stats: HourlyStatItem[];
  best_hour: HourlyStatItem | null;
  worst_hour: HourlyStatItem | null;
}

// ── Pipeline reasoning interfaces for LiveTradeReasoningWidget ───────────────

export interface AgentAnalystReport {
  regime?: string;
  stc_val?: number;
  signal?: string;
  confidence?: number;
  reasoning?: string;
  sentiment?: string;
  bias?: string;
  summary?: string;
  current_price?: number;
}

export interface DebateResult {
  verdict?: string;
  debate_score?: number;
  bull_score?: number;
  bear_score?: number;
  bull_weakest_point?: string;
  bear_weakest_point?: string;
  rounds_completed?: number;
}

export interface TradeDecisionSnapshot {
  action?: string;
  limit_price?: number;
  stop_price?: number;
  target_price?: number;
  confidence?: number;
  reasoning?: string;
}

export interface PipelineDecisionSnapshot {
  trade_decision?: TradeDecisionSnapshot;
  risk_decision?: { approved?: boolean; reason?: string; checks_passed?: number };
  fund_decision?: { approved?: boolean; final_conviction?: number; reasoning?: string };
  debate_result?: DebateResult;
  analyst_reports?: {
    technical?: AgentAnalystReport;
    news?: AgentAnalystReport;
    social?: AgentAnalystReport;
    fundamental?: AgentAnalystReport;
  };
  confidence?: number;
  boosted_confidence?: number;
  summary?: string;
  errors?: string[];
}

export interface RecentPipelineDecision {
  approval_id: string;
  symbol: string;
  action: string;
  quantity?: number;
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  created_at: string;
  status: string;
  pipeline_snapshot?: PipelineDecisionSnapshot;
}

// ── TradingView Bridge ──────────────────────────────────────────────────
export interface TVBridgeSnapshot {
  symbol: string;
  stc_value: number | null;
  stc_state: string | null;
  composite_score: number | null;
  regime: string | null;
  atr_value: number | null;
  ib_high: number | null;
  ib_low: number | null;
  ib_range: number | null;
  phase_oscillator: number | null;
  is_compressed: boolean;
  corey_score: number | null;
  corey_bias: string | null;
  vwap: number | null;
  data_quality: "live" | "stale" | "unavailable";
}

export interface TVBridgeHealth {
  available: boolean;
  cli_found: boolean;
  cdp_connected: boolean;
}

export async function fetchTVSnapshot(symbol: string): Promise<TVBridgeSnapshot> {
  return fetchEngine<TVBridgeSnapshot>(
    `/tv/snapshot?symbol=${encodeURIComponent(symbol)}`
  );
}

export async function fetchTVHealth(): Promise<TVBridgeHealth> {
  return fetchEngine<TVBridgeHealth>("/tv/health");
}

export interface RecentPipelineReasoningResponse {
  decisions: RecentPipelineDecision[];
  count: number;
}
export interface ShadowMetricsResponse {
  count: number;
  total_pnl: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
}

export async function fetchShadowMetrics(strategyName?: string): Promise<ShadowMetricsResponse> {
  const q = strategyName ? `?strategy_name=${encodeURIComponent(strategyName)}` : "";
  return fetchEngine<ShadowMetricsResponse>(`/pipeline/shadow-metrics${q}`);
}

export interface Pm2StatusResponse {
  found: boolean;
  status?: string;
  restart_count?: number;
  unstable_restarts?: number;
  uptime_ms?: number;
  memory_mb?: number;
  cpu_pct?: number;
  pid?: number;
  note?: string;
  error?: string;
}

export async function fetchPm2Status(): Promise<Pm2StatusResponse> {
  return fetchEngine<Pm2StatusResponse>("/health/pm2");
}

export interface OpenPositionsResponse {
  positions: Array<{
    symbol: string;
    action: string;
    quantity: number;
    entry_price: number;
    stop_loss?: number;
    broker_stp_order_id?: string;
    unrealized_pnl?: number;
  }>;
  count: number;
}

export async function fetchOpenPositions(): Promise<OpenPositionsResponse> {
  return fetchEngine<OpenPositionsResponse>("/portfolio/paper/positions");
}
