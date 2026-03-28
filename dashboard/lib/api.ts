// All calls proxy through Next.js rewrites → http://localhost:8010
const ENGINE = "/api/engine";

export async function fetchEngine<T>(path: string): Promise<T> {
  const res = await fetch(`${ENGINE}${path}`, { cache: "no-store" });
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
