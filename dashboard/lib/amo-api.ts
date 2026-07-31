// Read-only client for the amo-arbitrage system, proxied server-side through
// /api/amo (see app/api/amo/[...path]/route.ts) to avoid CORS. The two trading
// systems stay independent — this is observability-only for the Trust Pane.
const AMO = "/api/amo";
const FETCH_TIMEOUT_MS = 15000;

export async function fetchAmo<T = unknown>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${AMO}${path}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`amo error ${res.status}: ${path}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

/** GET /api/health on amo-arbitrage. */
export interface AmoScheduledJob {
  id: string;
  next_run: string;
}

export interface AmoHealthResponse {
  status: string;
  version?: string;
  time?: string;
  scheduler_running?: boolean;
  scheduled_jobs?: number;
  jobs?: AmoScheduledJob[];
}

export async function fetchAmoHealth(): Promise<AmoHealthResponse> {
  return fetchAmo<AmoHealthResponse>("/api/health");
}

// ── Edge verdict ──────────────────────────────────────────────────────────────
// GET /api/edge-verdict — which backtested strategies survive amo's family-wide
// Benjamini-Hochberg FDR gate (the same multiple-testing correction that decides
// what becomes 'validated'/Kelly-sized). The endpoint is read-only and degrades
// to status "no_verdict_available" (still HTTP 200) when the backtests table is
// empty or unreachable, so the Trust Pane never has to special-case a 5xx.

export interface AmoValidatedStrategy {
  strategy: string;
  commodity_id: number | null;
  backtest_id: number | string | null;
  p_value: number | null;
  significant: boolean;
  edge_over_random: number | null;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  total_trades: number | null;
  win_rate: number | null;
}

export interface AmoEdgeVerdictResponse {
  validated: AmoValidatedStrategy[];
  n_validated: number;
  n_total: number;
  methodology: string;
  fdr_q: number | null;
  as_of: string | null;
  // "ok" | "no_verdict_available"; kept open for forward-compat.
  status: string;
}

export async function fetchAmoEdgeVerdict(): Promise<AmoEdgeVerdictResponse> {
  return fetchAmo<AmoEdgeVerdictResponse>("/api/edge-verdict");
}

// ── Commodities lookup ────────────────────────────────────────────────────────
// GET /api/commodities — id→symbol/name map so the edge verdict can render
// "LE / Live Cattle" instead of the opaque commodity_id the verdict returns.

export interface AmoCommodity {
  id: number;
  symbol: string;
  name: string;
}

export async function fetchAmoCommodities(): Promise<AmoCommodity[]> {
  return fetchAmo<AmoCommodity[]>("/api/commodities");
}

// ── Signal outcomes ───────────────────────────────────────────────────────────
// GET /api/signal-outcomes/aggregate — did amo's emitted setups actually pay
// off? hit_rate counts target1/target2 hits over all EVALUATED outcomes;
// P&L is hypothetical (amo has no execution). Degrades to provisioned:false
// (still HTTP 200) when the phase7 migration hasn't been applied.

export interface AmoOutcomeCommodityBreakdown {
  total: number;
  hit_rate: number | null;
  avg_pnl_pct: number | null;
}

export interface AmoSignalOutcomesAggregate {
  hit_rate: number | null;
  avg_hypothetical_pnl_pct: number | null;
  total_evaluated: number;
  breakdown_by_commodity: Record<string, AmoOutcomeCommodityBreakdown>;
  count_by_hit: Record<string, number>;
  provisioned?: boolean;
}

export async function fetchAmoSignalOutcomesAggregate(): Promise<AmoSignalOutcomesAggregate> {
  return fetchAmo<AmoSignalOutcomesAggregate>("/api/signal-outcomes/aggregate");
}

// ── Strategy scoreboard ───────────────────────────────────────────────────────
// GET /api/scoreboard — each validated strategy's backtest screen beside its
// live forward record, plus evidence gathered toward Kelly graduation. Same
// gate as /api/edge-verdict — never a re-implemented notion of "validated".

export interface AmoScoreboardStrategy {
  strategy: string;
  commodity_id: number | null;
  symbol: string | null;
  verdict: string | null;
  forward_confirmed: boolean | null;
  kelly_sized: boolean | null;
  backtest_pf: number | null;
  backtest_win_rate: number | null;
  backtest_trades: number | null;
  forward_pf: number | null;
  forward_win_rate: number | null;
  forward_avg_pnl_pct: number | null;
  pf_vs_backtest: number | null;
  n_closed: number;
  n_open: number;
  evidence_gathered: number;
  evidence_target: number;
  graduation_ready: boolean;
  graduation_reason: string | null;
}

export interface AmoScoreboardResponse {
  strategies: AmoScoreboardStrategy[];
  n_strategies: number;
  as_of: string | null;
  min_closed: number;
  methodology: string;
  status: string;
  available: boolean;
}

export async function fetchAmoScoreboard(): Promise<AmoScoreboardResponse> {
  return fetchAmo<AmoScoreboardResponse>("/api/scoreboard");
}

// ── Actionable-now board ──────────────────────────────────────────────────────
// GET /api/actionable — live derived status per active setup (distance to
// entry, R-multiple, status chip). Kelly is withheld server-side for anything
// not validated; unvalidated items arrive with exploratory=true.

export interface AmoActionableItem {
  id: number | string | null;
  commodity_id: number | null;
  symbol: string;
  direction: string;
  setup_date: string | null;
  composite_score: number | null;
  setup_quality: string | null;
  validation_status: string;
  exploratory: boolean;
  status: string;
  entry_price: number | null;
  stop_loss: number | null;
  target_1: number | null;
  latest_price: number | null;
  as_of: string | null;
  distance_pct: number | null;
  distance_atr: number | null;
  distance_ticks: number | null;
  planned_rr: number | null;
  current_r: number | null;
  notional_per_contract: number | null;
  kelly_fraction: number | null;
  age_days: number | null;
}

export interface AmoActionableResponse {
  items: AmoActionableItem[];
  as_of: string | null;
  available: boolean;
}

export async function fetchAmoActionable(): Promise<AmoActionableResponse> {
  return fetchAmo<AmoActionableResponse>("/api/actionable");
}
