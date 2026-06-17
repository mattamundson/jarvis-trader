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
