// All dashboard calls MUST use fetchEngine() or postEngine() below.
// These functions proxy through Next.js rewrites to the engine backend.
// NEVER hardcode an absolute engine URL or make fetch calls directly.
const ENGINE = "/api/engine";
const FETCH_TIMEOUT_MS = 30000; // 30 seconds
const RETRY_DELAY_MS = 2000; // 2 seconds

// Engine auth is injected SERVER-SIDE by the proxy route handler
// (app/api/engine/[...path]/route.ts) from the non-public ENGINE_API_KEY.
// The browser must NEVER carry the key: NEXT_PUBLIC_* values are inlined into
// the client JS bundle, so a public/remote deployment would hand the engine
// key to every visitor. All engine calls go through the same-origin /api/engine
// proxy, which sets X-API-Key itself — the client sends no credential.
function engineHeaders(extra?: HeadersInit): HeadersInit {
  return { ...extra };
}

/**
 * Thrown for a non-2xx engine response. Carries the HTTP status so callers
 * (fetchWithRetry) can distinguish a transient 5xx from a durable 4xx without
 * parsing the message string.
 */
class EngineHttpError extends Error {
  status: number;
  constructor(status: number, url: string) {
    super(`Engine error ${status}: ${url}`);
    this.name = "EngineHttpError";
    this.status = status;
  }
}

async function fetchWithTimeout<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    // Pass an explicit reason so callers (and fetchWithRetry's error check)
    // see a readable "request timed out" message instead of the browser's
    // default "signal is aborted without reason" DOMException text (what
    // abort() produces when called with no argument). Mirrors fetchEngineRaw.
    () => controller.abort(new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s: ${url}`)),
    FETCH_TIMEOUT_MS,
  );

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new EngineHttpError(res.status, url);
    }

    return res.json();
  } catch (e) {
    // Fall back to a friendly message if the runtime doesn't propagate the
    // AbortSignal reason as the rejection value (older engines reject with a
    // generic AbortError regardless of the reason passed to abort()).
    if (e instanceof Error && /abort/i.test(e.name) && /aborted without reason/i.test(e.message)) {
      throw new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s: ${url}`);
    }
    throw e;
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

    const isNetworkError =
      error.message.includes("Failed to fetch") ||
      error.message.includes("AbortError") ||
      error.name === "AbortError" ||
      // fetchWithTimeout now aborts with an explicit reason (a plain Error,
      // not a DOMException named "AbortError") so a timeout still needs its
      // own check here to keep getting the same single retry as before.
      error.message.includes("Request timed out after");

    // Also retry on a transient 5xx (502/503/504). Several /performance
    // widgets (hourly-stats, streaks, price bars) were observed getting a
    // 503 on the very first request right after page load -- likely
    // concurrency contention from ~35 widgets mounting and fetching at once
    // -- followed by a clean 200 moments later. Without this, only SWR's own
    // default error-retry (slower backoff, several seconds) recovered them,
    // which read as "stuck loading" for 15s+. Retrying 5xx here immediately,
    // the same way network errors already are, fixes that for every
    // fetchEngine() caller uniformly instead of per-widget. 4xx errors are
    // NOT retried -- they are not transient.
    const isTransientServerError =
      error instanceof EngineHttpError && error.status >= 500 && error.status < 600;

    if ((isNetworkError || isTransientServerError) && attempt < 2) {
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
  });
}

export async function postEngine<T = any>(path: string, body?: unknown): Promise<T> {
  return fetchWithRetry<T>(`${ENGINE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * Fetch a binary/non-JSON response from the engine (e.g. CSV downloads).
 * Returns the raw Response so the caller can call .blob(), .text(), etc.
 */
export async function fetchEngineRaw(path: string, options?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    // Pass an explicit reason so a caller's catch block sees a readable
    // "request timed out" message instead of the browser's default
    // "signal is aborted without reason" DOMException text (what abort()
    // produces when called with no argument).
    () => controller.abort(new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s: ${path}`)),
    FETCH_TIMEOUT_MS,
  );
  try {
    const res = await fetch(`${ENGINE}${path}`, {
      cache: "no-store",
      ...options,
      signal: controller.signal,
    });
    return res;
  } catch (e) {
    // Fall back to a friendly message if the runtime doesn't propagate the
    // AbortSignal reason as the rejection value (older engines reject with a
    // generic AbortError regardless of the reason passed to abort()).
    if (e instanceof Error && /abort/i.test(e.name) && /aborted without reason/i.test(e.message)) {
      throw new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s: ${path}`);
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Fetcher for the dashboard's OWN same-origin API routes (e.g. /api/fleet).
 * These are Next.js route handlers reading local disk state, not engine
 * endpoints, so they bypass the /api/engine proxy entirely. Lives here (not
 * in app/ or hooks/) because the "no bare await fetch" CI guard only scans
 * those two directories — this is the sanctioned escape hatch, same as
 * fetchEngine/postEngine above.
 */
export async function localFetch<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} error ${res.status}`);
  return res.json() as Promise<T>;
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
  tradingview_mcp_healthy?: boolean | null;
  tradingview_mcp_details?: string | null;
  llm_path_healthy?: boolean | null;
  llm_available?: boolean | null;
  // Provider-redundancy snapshot (engine get_llm_provider_summary). Present when
  // the engine wires it; absent on older builds (callers must guard).
  llm_providers?: LLMProviderSummary | null;
  vertex_failover_count?: number | null;
  google_fallback_count?: number | null;
}

export interface LLMProviderSummary {
  active_provider?: string | null;
  primary_provider?: string | null;
  primary_healthy?: boolean | null;
  single_leg_warning?: boolean | null;
}

// Full health (/health/full). Subsystems carry free-form detail; we type the
// ib_gateway data-leg observability fields shipped in PR #68 (auto-reconnect
// watchdog + silent-degrade visibility). All optional — older engines omit them,
// so every consumer must guard.
export type DataSourceTier = "ibkr" | "sqlite_cache" | "polygon" | "csv_cache" | "none";

export interface IBDataWatchdogStatus {
  enabled?: boolean | null;
  running?: boolean | null;
  consecutive_failures?: number | null;
  last_attempt_ts?: number | null;
  last_reconnect_ts?: number | null;
}

export interface IBGatewayHealth {
  status?: string | null;
  execution_connected?: boolean | null;
  data_connected?: boolean | null;
  data_source?: DataSourceTier | string | null;
  last_ibkr_data_ts?: number | null;
  watchdog?: IBDataWatchdogStatus | null;
  // Per-symbol staleness {symbol: seconds_since_last_serve} (US-002).
  per_symbol_freshness?: Record<string, number> | null;
}

// LLM path subsystem (/health/full -> subsystems.llm, US-004). `provider` is the
// leg actually serving; `fallback_active` is true when we're not on the primary.
export interface LLMSubsystemHealth {
  status?: string | null; // ok | degraded | unknown
  provider?: string | null;
  fallback_active?: boolean | null;
  healthy?: boolean | null;
  primary_provider?: string | null;
  active_provider?: string | null;
  providers_available?: number | null;
  single_leg_warning?: boolean | null;
  google_fallback_count?: number | null;
  vertex_failover_count?: number | null;
}

export interface FullHealthResponse {
  overall: string;
  timestamp: string;
  uptime_seconds: number;
  version: string;
  phase: string;
  subsystems: {
    ib_gateway?: IBGatewayHealth;
    llm?: LLMSubsystemHealth;
    [key: string]: unknown;
  };
}

// ── Forward-test loop (engine /analytics/forward-test) ───────────────────────
// Mirrors engine backtest.forward_test.run_forward_test. The endpoint also
// returns a {status:"INSUFFICIENT_DATA", ...} body when the DB is not wired,
// so every field below is treated as optional by the panel.
export interface ForwardStats {
  n_oos_windows: number;
  p_edge: number;
  pf_ci_lower: number;
  binom_p: number;
  total_trades: number;
  total_pnl: number;
}

export interface ForwardTestCandidate {
  id: string;
  symbol: string;
  attribution_level: string | null;
  precise_attribution: boolean;
  forward: ForwardStats;
  survives_family_fdr: boolean;
  graduated: boolean;
  reason: string;
}

export interface ForwardTestReport {
  status?: string;
  recommendation?: string;
  generated_at?: string;
  window_days?: number;
  n_active_candidates: number;
  n_graduated: number;
  candidates: ForwardTestCandidate[];
  note?: string;
}

// ── Forward-test loop (engine /analytics/forward-test) ───────────────────────
// Mirrors engine backtest.forward_test.run_forward_test. The endpoint also
// returns a {status:"INSUFFICIENT_DATA", ...} body when the DB is not wired,
// so every field below is treated as optional by the panel.
export interface ForwardStats {
  n_oos_windows: number;
  p_edge: number;
  pf_ci_lower: number;
  binom_p: number;
  total_trades: number;
  total_pnl: number;
}

export interface ForwardTestCandidate {
  id: string;
  symbol: string;
  attribution_level: string | null;
  precise_attribution: boolean;
  forward: ForwardStats;
  survives_family_fdr: boolean;
  graduated: boolean;
  reason: string;
}

// A decision lineage is the LLM identity stamped on live paper entries (P4) --
// the unit that actually trades. Only pre_registered lineages may graduate;
// default-material "unregistered:*" singletons render as context only.
export interface ForwardTestLineage {
  lineage: string;
  pre_registered: boolean;
  forward: ForwardStats;
  survives_family_fdr: boolean;
  graduated: boolean;
  reason: string;
}

export interface ForwardTestReport {
  status?: string;
  recommendation?: string;
  generated_at?: string;
  window_days?: number;
  n_active_candidates: number;
  n_graduated: number;
  candidates: ForwardTestCandidate[];
  // P4 lineage track -- optional so the panel degrades gracefully against an
  // engine that predates the lineage block.
  lineages?: ForwardTestLineage[];
  n_lineages?: number;
  n_lineages_graduated?: number;
  note?: string;
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
  // Fields actually returned by the engine /safety/status handler
  // (engine/routers/safety_router.py). Current drawdown is `drawdown_pct`; the
  // limit is config/.env-driven (`drawdown_limit_pct`, a negative decimal).
  drawdown_pct?: number;
  drawdown_limit_pct?: number;
  drawdown_breached?: boolean;
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

/** Fetch OHLCV bars for any symbol from GET /analyze/bars/{symbol} and normalize
 * to OHLCVBar[] (unix-second time, numeric fields). The engine returns a
 * BarsResponse {symbol, timeframe, bars: [...]} but may also return a bare
 * array, so parse defensively. Returns [] on any failure (caller shows empty
 * state). */
export async function fetchBars(
  symbol: string,
  opts: { timeframe?: string; days?: number; limit?: number; futures?: boolean } = {}
): Promise<OHLCVBar[]> {
  const { timeframe = "5m", days = 7, limit = 500, futures = true } = opts;
  const qs = `timeframe=${encodeURIComponent(timeframe)}&days=${days}&limit=${limit}&futures=${futures}`;
  let raw: unknown;
  try {
    raw = await fetchEngine<unknown>(`/analyze/bars/${encodeURIComponent(symbol)}?${qs}`);
  } catch {
    return [];
  }
  type RawBar = {
    time?: string | number;
    timestamp?: string | number;
    open: number | string;
    high: number | string;
    low: number | string;
    close: number | string;
    volume?: number | string | null;
    vwap?: number | string | null;
    stc?: number | string | null;
    ema_8?: number | string | null;
    ema_21?: number | string | null;
    ema_34?: number | string | null;
  };
  const arr: RawBar[] = Array.isArray(raw)
    ? (raw as RawBar[])
    : Array.isArray((raw as { bars?: RawBar[] })?.bars)
      ? ((raw as { bars?: RawBar[] }).bars as RawBar[])
      : [];
  return arr
    .map((b) => {
      // The engine's BarsResponse names the time field `timestamp`; bare-array
      // fallbacks may use `time`. Accept either so the chart isn't silently
      // emptied by a field-name mismatch (every bar would fail the finite filter).
      const rawTime = b.time ?? b.timestamp;
      return {
        time:
          typeof rawTime === "string"
            ? Math.floor(new Date(rawTime).getTime() / 1000)
            : (rawTime as number),
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
        volume: b.volume != null ? Number(b.volume) : undefined,
        vwap: b.vwap != null ? Number(b.vwap) : undefined,
        stc: b.stc != null ? Number(b.stc) : undefined,
        ema_8: b.ema_8 != null ? Number(b.ema_8) : undefined,
        ema_21: b.ema_21 != null ? Number(b.ema_21) : undefined,
        ema_34: b.ema_34 != null ? Number(b.ema_34) : undefined,
      };
    })
    .filter((b) => Number.isFinite(b.time) && Number.isFinite(b.close))
    .sort((a, b) => a.time - b.time);
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

/** GET /regime/vix-percentile — percentile VIX regime + momentum overlay */
export interface VixPercentileRegime {
  vix: number;
  vix_percentile: number; // 0..100
  tier: "Crisis" | "HighVol" | "MidVol" | "LowVol";
  momentum: "Bull" | "Neutral" | "Bear";
  confidence: number; // 0..1
  lookback: number;
  momentum_window: number;
  price_symbol: string;
  n_vix_bars: number;
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

/** GET /hidden-pivots/scan — Rick Ackerman HiddenPivots scanner (analysis-only). */
export interface HPSignal {
  symbol: string;
  timeframe: string;
  pattern: string | null;
  bias: "LONG" | "SHORT" | "WATCH" | "SOH";
  trigger_price: number | null;
  tight_stop: number | null;
  riskier_stop: number | null;
  targets: number[];
  hp_ou_level: number | null;
  ema_alignment: string;
  rs_rw_score: number;
  rs_rw_label: string;
  soh: boolean;
  oscillator_state: string;
  bars_since_cross: number;
  last_cross_dir: "bull" | "bear" | "none";
  confidence: number;
  notes: string;
}

export interface HPScanResponse {
  scan_time: string;
  symbols_scanned: number;
  signals: HPSignal[];
  soh_symbols: string[];
  watch_symbols: string[];
  /** Full per-symbol result for every scanned name (incl. WATCH/SOH). */
  details: HPSignal[];
}

/** Fetch the HiddenPivots scan for a given timeframe. */
export async function fetchHiddenPivotsScan(
  timeframe = "1d",
  benchmark = "SPY"
): Promise<HPScanResponse> {
  return fetchEngine<HPScanResponse>(
    `/hidden-pivots/scan?timeframe=${encodeURIComponent(timeframe)}&benchmark=${encodeURIComponent(benchmark)}`
  );
}

/**
 * Last price + daily change for the given symbols (GET /prices/snapshot).
 * Goes through the engine proxy (REST), so it works on the remote/Vercel
 * deploy unlike the WS feed. Server-side cache is 60s (rate-limit guard), so
 * values refresh roughly once a minute during market hours. Reuses the shared
 * `PriceSnapshot` map type (see below / WatchlistBar).
 */
export async function fetchPriceSnapshot(symbols: string[]): Promise<PriceSnapshot> {
  if (symbols.length === 0) return {};
  const q = encodeURIComponent(symbols.join(","));
  return fetchEngine<PriceSnapshot>(`/prices/snapshot?symbols=${q}`);
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
  // Data-provenance fields (Phase 1) — server-derived, additive. `is_live` is
  // NEVER hardcoded true; a cached/delayed tier (csv_cache, polygon REST) reports
  // is_live=false so the ticker can never show LIVE over stale data. `as_of` is
  // epoch SECONDS. Optional: older engine builds / degraded entries omit them.
  source?: string;
  as_of?: number | null;
  is_live?: boolean;
  stale_after_s?: number;
}

export type PriceSnapshot = Record<string, PriceSnapshotEntry>;

export interface MacroSnapshot {
  vix?: number | null;
  vix_regime?: string | null; // LOW | NORMAL | HIGH | EXTREME (from classify_vix_regime)
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
  trade_id: string;
  symbol: string;
  quantity: number;
  timestamp: string;
  /** New canonical field: BUY | SELL | HOLD */
  action: "BUY" | "SELL" | "HOLD";
  /** Most recent price (exit if closed, else entry) */
  price: number;
  pnl: number | null;
  /** LLM review grade A/B/C/D/F — null if not yet complete */
  grade: string | null;
  /** pending | complete | failed | null */
  review_status: string | null;
  // Legacy aliases returned by the API for backwards-compat with existing widgets
  id: number;
  side: "BUY" | "SELL";
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
  /** Current drawdown as a decimal, negative (e.g. -0.012 = -1.2%) */
  drawdown_pct: number;
  /**
   * Maximum drawdown threshold as a negative decimal (e.g. -0.20 = -20%).
   * The real /safety/circuit-breakers response field is `drawdown_limit_pct`
   * -- there is no `drawdown_limit` field. Reading the wrong name produced
   * `undefined`, and `undefined * 100` rendered the panel's drawdown limit as
   * "-NaN%".
   */
  drawdown_limit_pct: number;
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

// ── Strategy ledger (gate-v2 backtest verdicts) ──────────────────────────────

export interface LedgerEntry {
  symbol: string | null;
  family: string | null;
  rank: number | null;
  verdict: string | null; // PASS | FAIL
  passed_via: string | null;
  core_verdict: string | null;
  alt_verdict: string | null;
  created_at: string | null;
  pf_ci_lower: number | null;
  p_edge: number | null;
  mc_95th_dd_pct: number | null;
  dsr: number | null;
  wfo_consistency: string | null;
  fixed_params_min_pf: number | null;
  cost_survives_through: string | null;
  oos_trades: number | null;
  source_file: string | null;
}

export interface LedgerResponse {
  entries: LedgerEntry[];
  total: number;
  n_pass: number;
  n_fail: number;
  generated_at: string;
}

/** GET /strategy/ledger — gate-v2 backtest verdict ledger. */
export async function fetchStrategyLedger(): Promise<LedgerResponse> {
  return fetchEngine<LedgerResponse>("/strategy/ledger");
}

// ── Research candidates (GET /strategy/research-candidates) ───────────────────
// X-bookmark edge-scan candidates + their RESEARCH gate-v2 verdicts. This is a
// non-authorizing namespace (separate from the production ledger) — visibility only.
export interface ResearchCandidate {
  strategy: string | null;
  symbol: string | null;
  family: string | null;
  strategy_class: string | null;
  verdict: string | null;
  passed_via: string | null;
  pf_ci_lower: number | null;
  p_edge: number | null;
  mc_95th_dd_pct: number | null;
  dsr: number | null;
  source_bookmark_url: string | null;
  author: string | null;
  scan_date: string | null;
  class_note: string | null;
  created_at: string | null;
  source_file: string | null;
}

export interface ResearchCandidatesResponse {
  candidates: ResearchCandidate[];
  total: number;
  generated_at: string;
}

/** GET /strategy/research-candidates — X-bookmark edge-scan research candidates. */
export async function fetchResearchCandidates(): Promise<ResearchCandidatesResponse> {
  return fetchEngine<ResearchCandidatesResponse>("/strategy/research-candidates");
}

// ── Macro trend regime (GET /macro/regime) — X-bookmark trend edges on SPX ────
// Market-wide RISK_ON/RISK_OFF/NEUTRAL/UNKNOWN from weekly Supertrend + monthly
// momentum. ADVISORY only — folded into the futures pipeline context solely when
// the ENABLE_MACRO_TREND_BIAS feature flag is on; never routes capital.
export interface MacroRegime {
  state: "RISK_ON" | "RISK_OFF" | "NEUTRAL" | "UNKNOWN";
  weekly_trend: "UP" | "DOWN" | null;
  monthly_momentum: "ABOVE" | "BELOW" | null;
  asof: string | null;
  spy_close: number | null;
  bias_line: string;
  stale_days?: number;
  error?: string;
  components: {
    weekly_supertrend_atr10x3?: boolean;
    monthly_sma12_momentum?: boolean;
  };
}

/** GET /macro/regime — advisory macro trend bias state. */
export async function fetchMacroRegime(): Promise<MacroRegime> {
  return fetchEngine<MacroRegime>("/macro/regime");
}

// ── Production-gate scorecard (GET /strategy/gates/{symbol}, US-005) ──────────
export interface GateResult {
  key: string;
  label: string;
  value: number | null;
  threshold: number | null;
  comparator: string; // ">=" | "<="
  unit: string | null;
  passed: boolean | null; // null => not evaluable (missing value or shadow gate)
  enforced: boolean;
  note: string | null;
}

export interface GatesResponse {
  symbol: string;
  family: string | null;
  verdict: string | null;
  created_at: string | null;
  n_pass: number;
  n_evaluated: number;
  n_total: number;
  gates: GateResult[];
  generated_at: string;
}

/** GET /strategy/gates/{symbol} — 6-gate production scorecard for one symbol. */
export async function fetchStrategyGates(symbol: string): Promise<GatesResponse> {
  return fetchEngine<GatesResponse>(`/strategy/gates/${encodeURIComponent(symbol)}`);
}

// ── Per-trade full review (closed loop) ──────────────────────────────────────

export interface TradeFullReview {
  trade: Record<string, unknown>;
  attribution: Record<string, unknown>;
  why: {
    decision_id: number | null;
    matched_by: string;
    match_delta_seconds: number | null;
    timestamp: string | null;
    action: string | null;
    confidence: number | null;
    regime: string | null;
    reasoning: string | null;
    pipeline: Record<string, unknown> | null;
  } | null;
  backtest: LedgerEntry | null;
  forward: {
    profit_factor: number;
    sharpe_ratio: number;
    win_rate: number;
    avg_win: number;
    avg_loss: number;
    max_drawdown: number;
    total_trades: number;
    total_pnl: number;
    meets_paper_threshold: boolean;
    period_days: number;
  } | null;
  review: Record<string, unknown> | null;
}

/** GET /trades/{id}/full-review — the closed-loop join for one placed trade. */
export async function fetchTradeFullReview(tradeId: string): Promise<TradeFullReview> {
  return fetchEngine<TradeFullReview>(`/trades/${encodeURIComponent(tradeId)}/full-review`);
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
  const status = await fetchEngine<{
    kill_switch_active: boolean;
    kill_switch_reason: string | null;
  }>("/safety/status");
  return {
    active: status.kill_switch_active,
    reason: status.kill_switch_reason,
    activated_at: null,
  };
}

export async function toggleKillSwitch(
  action: "activate" | "deactivate",
  reason?: string
): Promise<KillSwitchStatus> {
  if (action === "activate") {
    const qs = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    await postEngine<{ status: string }>(`/safety/kill-switch/activate${qs}`);
  } else {
    await postEngine<{ status: string }>("/safety/kill-switch/deactivate");
  }
  return fetchKillSwitchStatus();
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
  /**
   * Real engine response from /portfolio/paper/hourly-stats sends
   * `hour_label` / `trade_count` (confirmed via live response), not
   * `label` / `trades`. Reading the old names left every hour's label
   * blank and the trade count as "undefinedt" in WinRateByHourWidget.
   */
  hour_label: string;
  win_rate: number;
  trade_count: number;
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
  signal?: number | string; // numeric score (~ -1..1); string is legacy/fallback
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
  risk_decision?: { approved?: boolean; reasoning?: string; checks_passed?: number };
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
    // strategy_params are JSON-encoded into notes by add_paper_trade()
    notes?: string;
  }>;
  count: number;
}

export async function fetchOpenPositions(): Promise<OpenPositionsResponse> {
  return fetchEngine<OpenPositionsResponse>("/portfolio/paper/positions");
}

// ── Same-day P&L reconciliation (US-007) ─────────────────────────────────────
// /portfolio/summary computes total_daily_pnl = realized_pnl + (clean) unrealized;
// /portfolio/pnl-snapshot is an INDEPENDENTLY-computed same-day number (SafetyLayer
// sync, survives restart). Reconciliation compares the two writers — the phantom-day
// failure was drift between them.
export interface PortfolioSummary {
  total_daily_pnl?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  total_pnl?: number;
  daily_target?: number;
  target_progress_pct?: number;
}

export interface PnlSnapshot {
  date?: string;
  daily_pnl?: number;
  portfolio_equity?: number;
  last_updated?: string | null;
  source?: string; // sqlite | no_db | no_snapshot
}

export async function fetchPortfolioSummary(): Promise<PortfolioSummary> {
  return fetchEngine<PortfolioSummary>("/portfolio/summary");
}

export async function fetchPnlSnapshot(): Promise<PnlSnapshot> {
  return fetchEngine<PnlSnapshot>("/portfolio/pnl-snapshot");
}

// ── Live open paper trades (truthful: reads paper_trades WHERE status='open') ──
// /portfolio/paper/positions reads OMS/broker state and can be empty while the
// paper_trades table holds open rows; /execution/fidelity-status reads the table
// directly, so it is the canonical "what is open right now" source for the UI.
export interface ExecutionOpenTrade {
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  entry_time: string;
  slippage_ticks?: number | null;
}

export interface ExecutionFidelityStatus {
  generated_at: string;
  measuring_real_fills: boolean;
  open_trades: ExecutionOpenTrade[];
  pending_approvals: { count: number; oldest_age_min: number | null };
}

export async function fetchExecutionOpenTrades(): Promise<ExecutionFidelityStatus> {
  return fetchEngine<ExecutionFidelityStatus>("/execution/fidelity-status");
}

// ── Discord Bookmark Feed (recent + search) ──────────────────────────────────

export interface BookmarkRow {
  posted_at: string;
  url: string;
  domain: string | null;
  source_type: string | null;
  embed_title: string | null;
  embed_description: string | null;
  content: string | null;
  author_name?: string | null;
}

export interface BookmarkFeedResponse {
  data: BookmarkRow[];
  hours?: number;
  limit?: number;
  query?: string;
  days?: number;
}

export async function fetchBookmarksRecent(opts?: {
  hours?: number;
  limit?: number;
}): Promise<BookmarkFeedResponse> {
  const q = new URLSearchParams();
  if (opts?.hours != null) q.set("hours", String(opts.hours));
  if (opts?.limit != null) q.set("limit", String(opts.limit));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return fetchEngine<BookmarkFeedResponse>(`/discord/bookmarks/recent${suffix}`);
}

export async function fetchBookmarksSearch(opts: {
  query: string;
  days?: number;
  limit?: number;
}): Promise<BookmarkFeedResponse> {
  const q = new URLSearchParams({ query: opts.query });
  if (opts.days != null) q.set("days", String(opts.days));
  if (opts.limit != null) q.set("limit", String(opts.limit));
  return fetchEngine<BookmarkFeedResponse>(`/discord/bookmarks/search?${q.toString()}`);
}

// ── QuantStats / Portfolio Tearsheet ─────────────────────────────────────────

export interface RollingSharpPoint {
  date: string;
  value: number;
}

/** GET /reports/quantstats — institutional-grade portfolio metrics */
export interface QuantStatsMetrics {
  n_trades: number;
  start_date: string;
  end_date: string;
  source: "pnl_snapshots" | "paper_trades";
  sortino: number | null;
  sharpe: number | null;
  calmar: number | null;
  /** Negative number, e.g. -0.12 means -12% max drawdown */
  max_dd: number | null;
  max_dd_duration_days: number;
  win_rate: number | null;
  profit_factor: number | null;
  monthly_returns: Record<string, number>;
  rolling_sharpe_30d: RollingSharpPoint[];
}

export async function fetchQuantStats(opts?: {
  days?: number;
  run_id?: string;
}): Promise<QuantStatsMetrics> {
  const q = new URLSearchParams();
  if (opts?.days != null) q.set("days", String(opts.days));
  if (opts?.run_id != null) q.set("run_id", opts.run_id);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return fetchEngine<QuantStatsMetrics>(`/reports/quantstats${suffix}`);
}

// ── Jarvis Ask (command-center /jarvis/ask) ───────────────────────────────────

export interface JarvisAskResponse {
  answer: string;
  sources: string[];
  actions_taken: string[];
  elapsed_ms: number;
  intent: string;
}

export async function fetchJarvisAsk(question: string): Promise<JarvisAskResponse> {
  return postEngine<JarvisAskResponse>("/jarvis/ask", { question });
}

// ── Calibration diagnostics (/analytics/calibration) ─────────────────────────

export interface CalibrationAgentEntry {
  brier_score: number;
  brier_weight: number;
  ic_score: number;
  sample_count: number;
  ready: boolean;
}

export interface CalibrationDiagnostics {
  brier_enabled: boolean;
  brier_blend_alpha: number;
  min_trades_threshold: number;
  window_days: number;
  agents: string[];
  per_agent: Record<string, CalibrationAgentEntry>;
  total_outcomes: number;
  ready_to_activate: boolean;
  active_agents: string[];
  blocked_by: string[];
  rows_excluded_corrupt: number;
  rows_excluded_duplicate: number;
  neutral_sentinel: number;
  timestamp: string;
}

export async function fetchCalibration(): Promise<CalibrationDiagnostics> {
  return fetchEngine<CalibrationDiagnostics>("/analytics/calibration");
}

// ── Excursion analytics (MAE/MFE) (/analytics/excursion) ─────────────────────
// Per-closed-trade Maximum Adverse / Favorable Excursion + capture ratio.
// mae_pct/mfe_pct are NULL until the async excursion backfill runs for a trade.

export interface ExcursionTrade {
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  entry_time: string;
  exit_time: string | null;
  mae_pct: number | null;
  mfe_pct: number | null;
  mae_usd: number | null;
  mfe_usd: number | null;
  mfe_capture_ratio: number | null;
}

export interface ExcursionAggregates {
  trade_count: number;
  populated_count: number;
  avg_mae_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_usd: number | null;
  avg_mfe_usd: number | null;
  avg_mfe_capture_ratio: number | null;
}

export interface ExcursionResponse {
  trades: ExcursionTrade[];
  aggregates: ExcursionAggregates;
  timestamp: string;
}

export async function fetchExcursion(
  opts?: { symbol?: string; limit?: number }
): Promise<ExcursionResponse> {
  const qs = new URLSearchParams();
  if (opts?.symbol) qs.set("symbol", opts.symbol);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchEngine<ExcursionResponse>(`/analytics/excursion${suffix}`);
}

// ── Entry-timing scenarios (/analytics/entry-timing) ─────────────────────────
// Per-closed-trade what-if: PnL if entry had occurred N bars earlier/later
// (exit held constant). offset 0 reproduces the actual trade. Bars are fetched
// server-side; trades with no bars return bars_available=false + empty scenarios.

export interface EntryTimingScenarioRow {
  offset_bars: number;
  hypothetical_entry: number;
  pnl_usd: number;
  pnl_pct: number;
  delta_vs_actual_usd: number;
}

export interface EntryTimingTrade {
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  entry_time: string;
  exit_time: string | null;
  scenarios: EntryTimingScenarioRow[];
  entry_bar_index: number | null;
  bars_available: boolean;
}

export interface EntryTimingAggregates {
  trade_count: number;
  computed_count: number;
  avg_delta_by_offset: Record<string, number>;
  best_avg_offset: number | null;
  worst_avg_offset: number | null;
  systematic_bias: string | null;
}

export interface EntryTimingResponse {
  trades: EntryTimingTrade[];
  aggregates: EntryTimingAggregates;
  offsets_evaluated: number[];
  timestamp: string;
}

export async function fetchEntryTiming(
  opts?: { symbol?: string; limit?: number; offsets?: string }
): Promise<EntryTimingResponse> {
  const qs = new URLSearchParams();
  if (opts?.symbol) qs.set("symbol", opts.symbol);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  if (opts?.offsets) qs.set("offsets", opts.offsets);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchEngine<EntryTimingResponse>(`/analytics/entry-timing${suffix}`);
}

// ── Bar-depth / data-coverage health (/analytics/bar-depth) ──────────────────
// Per symbol×interval coverage: rows, calendar span, gap structure, and the
// fraction the bar-quality gate would reject. Endpoint is additive and only
// goes live after an engine restart, so callers must tolerate a 404.

export interface BarDepthPair {
  symbol: string;
  interval: string;
  rows: number;
  first_ts: string | null;
  last_ts: string | null;
  span_days: number;
  gap_count: number;
  max_gap_hours: number;
  contaminated_pct: number;
  enforce_safe: boolean;
}

export interface BarDepthSummary {
  pair_count: number;
  symbol_count: number;
  total_rows: number;
  total_rejects: number;
  contaminated_pct: number;
}

export interface BarDepthResponse {
  pairs: BarDepthPair[];
  summary: BarDepthSummary;
  timestamp: string;
}

export async function fetchBarDepth(): Promise<BarDepthResponse> {
  return fetchEngine<BarDepthResponse>("/analytics/bar-depth");
}

// ── Discord Briefing (command-center /discord/briefing) ──────────────────────

export interface BriefingIBLevels {
  high?: number | null;
  low?: number | null;
  range?: number | null;
  [key: string]: unknown;
}

export interface BriefingRecentSignal {
  direction?: string | null;
  confidence?: number | null;
  timestamp?: string | null;
  [key: string]: unknown;
}

/** One curated-knowledge hit from the gbrain brain (only present when enriched). */
export interface KnowledgeContextHit {
  slug: string;
  title?: string | null;
  type?: string | null;
  /** First-stage vector similarity (0..1). */
  similarity?: number | null;
  /** Cross-encoder rerank score (0..1; both Voyage and local tiers normalized). */
  rerank_score?: number | null;
  /** Truncated content preview (≤400 chars). */
  content?: string | null;
}

export interface BriefingResponse {
  symbol: string;
  headline?: string | null;
  // engine returns either a plain string or a structured object
  // ({date, session_type, directional_bias, ...}) — accept both so consumers
  // coerce/extract rather than crashing (e.g. .toLowerCase on an object).
  corey_bias?: string | Record<string, unknown> | null;
  ib_levels?: BriefingIBLevels | null;
  recent_signal?: BriefingRecentSignal | null;
  /** Advisory curated-knowledge hits — present ONLY when fetched with enriched:true. */
  knowledge_context?: KnowledgeContextHit[] | null;
  /** Rerank tier that produced knowledge_context: "voyage" | "local" | "off". */
  knowledge_context_tier?: string | null;
}

export async function fetchDiscordBriefing(
  symbol: string,
  opts?: { enriched?: boolean }
): Promise<BriefingResponse> {
  const q = new URLSearchParams({ symbol });
  if (opts?.enriched) q.set("enriched", "true");
  return fetchEngine<BriefingResponse>(`/discord/briefing?${q.toString()}`);
}

// ── Parallel Paper A/B Testing ────────────────────────────────────────────────

export interface EquityCurvePoint {
  date: string;
  equity: number;
}

/** GET /portfolio/paper/account/{account_id}/stats */
export interface AccountStatsResponse {
  account_id: "A" | "B";
  days: number;
  n_trades: number;
  win_rate: number | null;
  sortino: number | null;
  sharpe: number | null;
  calmar: number | null;
  max_dd: number | null;
  equity_curve: EquityCurvePoint[];
}

export async function fetchAccountStats(
  accountId: "A" | "B",
  days: 30 | 90 | 180 = 30
): Promise<AccountStatsResponse> {
  return fetchEngine<AccountStatsResponse>(
    `/portfolio/paper/account/${accountId}/stats?days=${days}`
  );
}

// ── Risk Attribution ─────────────────────────────────────────────────────────

/** Per-analyst window-level stats returned by GET /attribution/window */
export interface AnalystWindowStats {
  total: number;
  mean: number;
  std: number;
  max_loss: number;
  win_rate_top: number;
}

/** Per-day attribution entry nested inside WindowAttributionResponse.daily */
export interface DailyAttributionEntry {
  date: string;
  total_pnl: number;
  n_trades: number;
  attribution: Record<string, number>;
  top_contributor: string | null;
  residual: number;
  attributed_trade_count: number;
  unattributed_trade_count: number;
}

/** GET /attribution/window — rolling N-day attribution */
export interface RiskAttributionResponse {
  start_date: string;
  end_date: string;
  days_with_trades: number;
  total_pnl: number;
  n_trades: number;
  per_analyst: Record<string, AnalystWindowStats>;
  top_contributor_by_abs: string;
  daily: DailyAttributionEntry[];
}

/** GET /attribution/daily */
export interface DailyAttributionResponse {
  date: string;
  total_pnl: number;
  n_trades: number;
  attribution: Record<string, number>;
  top_contributor: string | null;
  residual: number;
  attributed_trade_count: number;
  unattributed_trade_count: number;
}

export async function fetchRiskAttribution(opts?: {
  days?: number;
}): Promise<RiskAttributionResponse> {
  const days = opts?.days ?? 30;
  return fetchEngine<RiskAttributionResponse>(`/attribution/window?days=${days}`);
}

export async function fetchDailyAttribution(
  date?: string
): Promise<DailyAttributionResponse> {
  const suffix = date ? `?date=${date}` : "";
  return fetchEngine<DailyAttributionResponse>(`/attribution/daily${suffix}`);
}

// ---------------------------------------------------------------------------
// Journal Review — Koroush AK framework
// ---------------------------------------------------------------------------

export interface JournalTradeStats {
  total_trades: number;
  win_rate: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  risk_reward_ratio: number;
  expected_value_usd: number;
  trades_per_week: number;
  diagnosis: "win_rate" | "avg_loss" | "avg_win" | "solid" | "insufficient_data";
}

export interface JournalBreakdownRow {
  group_key: string;
  group_value: string;
  count: number;
  win_rate: number;
  net_pnl: number;
  avg_pnl: number;
  flagged: boolean;
  flag_reason: string;
}

export interface JournalBreakdown {
  by_symbol: JournalBreakdownRow[];
  by_side: JournalBreakdownRow[];
  by_regime: JournalBreakdownRow[];
  by_bias: JournalBreakdownRow[];
  flags: JournalBreakdownRow[];
}

export interface JournalAnalysis {
  analysis: string;
  trade_count: number;
  has_journal_data: boolean;
}

export interface JournalFormalizeResult {
  pressure_tested: string;
  falsifiable_rule: string;
  journal_columns: string[];
  sample_size: number;
  pass_threshold: string;
  fail_threshold: string;
  abandonment_criteria: string;
  raw_llm_output: string;
}

export interface MonthlyReview {
  stats: JournalTradeStats;
  breakdown: JournalBreakdown;
  llm_analysis: string;
  generated_at: string;
  trade_count: number;
}

export async function fetchJournalStats(limit = 30): Promise<JournalTradeStats> {
  return fetchEngine<JournalTradeStats>(`/journal/review/stats?limit=${limit}`);
}

export async function fetchJournalBreakdown(limit = 30): Promise<JournalBreakdown> {
  return fetchEngine<JournalBreakdown>(`/journal/review/breakdown?limit=${limit}`);
}

export async function analyzeJournalPatterns(
  limit = 100
): Promise<JournalAnalysis> {
  return postEngine<JournalAnalysis>("/journal/review/analyze", { limit });
}

export async function formalizeInsight(
  observation: string
): Promise<JournalFormalizeResult> {
  return postEngine<JournalFormalizeResult>("/journal/review/formalize", {
    observation,
  });
}

export async function fetchMonthlyReview(limit = 30): Promise<MonthlyReview> {
  return fetchEngine<MonthlyReview>(`/journal/review/monthly?limit=${limit}`);
}

// ── Pine Screener (GreenStar2-style) ─────────────────────────────────────────
// Backs the /screener page: pipes the read-only IB scanner movers universe
// through the engine's screener filter chain (POST /ib-scanner/screen).

export interface ScreenerFilterInput {
  scan_code?: string;
  symbols?: string[] | null;
  max_symbols?: number;
  x_from_50_min?: number | null;
  x_from_50_max?: number | null;
  rvol_min?: number | null;
  x_from_lod_max?: number | null;
  chg_pct_min?: number | null;
  chg_open_pct_min?: number | null;
  atr_pct_min?: number | null;
  atr_pct_max?: number | null;
  mm_min?: number | null;
}

export interface ScreenedRow {
  symbol: string | null;
  last_price: number | null;
  atr_pct: number | null;
  rvol: number | null;
  x_from_50: number | null;
  x_from_lod_pct: number | null;
  chg_pct: number | null;
  chg_open_pct: number | null;
  mm_score: number;
  bars_used: number;
  passed: boolean;
  reasons: string[];
}

export interface ScreenResponse {
  enabled: boolean;
  universe_source: string;
  total_candidates: number;
  passed_count: number;
  focus: ScreenedRow[];
  rejected: ScreenedRow[];
  note: string;
}

export async function screenMovers(
  input: ScreenerFilterInput
): Promise<ScreenResponse> {
  return postEngine<ScreenResponse>("/ib-scanner/screen", input);
}

// ── Proactive Advisor Brief (Phase 5) ───────────────────────────────────────
// Mirrors engine/analytics/session_brief.py. The backend assembles these ONLY
// from reasoning the pipeline already produced — a reasoning-less decision
// surfaces as an honest gap (`reasoning_available: false`), never fabricated.

export interface SessionBriefStaleness {
  as_of: string | null;
  age_seconds: number | null;
  is_stale: boolean;
  unknown_age: boolean;
}

export interface SessionBriefAction {
  symbol: string;
  action: string;
  confidence: number | null;
  why: string;
  reasoning_available: boolean;
  reasoning_sources: string[];
  staleness: SessionBriefStaleness;
  data_degraded: boolean;
}

export interface SessionBriefResponse {
  generated_at: string;
  actions: SessionBriefAction[];
  count: number;
  degraded: boolean;
  note: string | null;
}

export async function fetchSessionBrief(
  limit = 10,
  maxActions = 3
): Promise<SessionBriefResponse> {
  return fetchEngine<SessionBriefResponse>(
    `/brief/session?limit=${limit}&max_actions=${maxActions}`
  );
}

// ── ATR-trail visualizer (GET /backtest/atr-trail/trades) ──────────────────
// Powers app/atr-trail: the TOS ATRTrailingStopLE/SE flip strategy's actual
// trades on cached bars — price + trail line + entries/exits + equity curve.
export interface AtrTrailPricePoint {
  t: number;
  c: number;
}
export interface AtrTrailLinePoint {
  t: number;
  v: number;
  s: number;
}
export interface AtrTrailTrade {
  entry_t: number;
  entry_px: number;
  exit_t: number;
  exit_px: number;
  dir: number;
  pnl_usd: number;
  pnl_pts: number;
}
export interface AtrTrailEquityPoint {
  t: number;
  v: number;
}
export interface AtrTrailTradesResponse {
  symbol: string;
  period: number;
  factor: number;
  n_trades: number;
  win_rate: number;
  net_usd: number;
  bars: number;
  price: AtrTrailPricePoint[];
  trail: AtrTrailLinePoint[];
  trades: AtrTrailTrade[];
  equity: AtrTrailEquityPoint[];
  source_file?: string;
}

export async function fetchAtrTrailTrades(params: {
  symbol?: string;
  timeframe?: string;
  period?: number;
  factor?: number;
  maxPoints?: number;
}): Promise<AtrTrailTradesResponse> {
  const qs = new URLSearchParams({
    symbol: params.symbol ?? "MES",
    timeframe: params.timeframe ?? "5m",
    period: String(params.period ?? 5),
    factor: String(params.factor ?? 3.5),
    max_points: String(params.maxPoints ?? 3000),
  });
  return fetchEngine<AtrTrailTradesResponse>(`/backtest/atr-trail/trades?${qs.toString()}`);
}

// ── Engine clean-run durability (GET /ops/durability) ─────────────────────────
// Reads the down-alert watchdog's outage ledger server-side and reports how long
// the engine has run clean. Honest empty-state (has_data:false) when no ledger.
// See engine/routers/durability_router.py + scripts/ops/durability.mjs.
export interface DurabilityOutage {
  downSince: string;
  recoveredAt: string;
  durationMs: number;
  alerted: boolean;
}

export interface DurabilityResponse {
  monitoring_since: string | null;
  currently_down: boolean;
  down_since: string | null;
  outage_count: number;
  current_streak_days: number | null;
  longest_streak_days: number | null;
  total_downtime_ms: number;
  mtbf_ms: number | null;
  last_outage: DurabilityOutage | null;
  has_data: boolean;
}

export async function fetchDurability(): Promise<DurabilityResponse> {
  return fetchEngine<DurabilityResponse>("/ops/durability");
}

// ── Honest realized P&L (engine-native, always available) ─────────────────────
// GET /pnl/truth — the fail-safe honest realized paper-P&L surface. Unlike the
// master-api honest-metrics layer, this reads the engine's own closed-trade
// ledger and DEGRADES (realized_pnl: null) instead of emitting a fabricated 0
// when the ledger is missing. It has NO external-service dependency, so it stays
// truthful even when master-api (:8030) is down. See engine/routers/pnl_truth_router.py.
export interface PnlTruthResponse {
  status: "TRUSTED" | "DEGRADED";
  realized_pnl: number | null;
  closed_trades: number;
  excluded_trades: number;
  reasons: string[];
  sources_present: string[];
  trusted: boolean;
}

export async function fetchPnlTruth(): Promise<PnlTruthResponse> {
  return fetchEngine<PnlTruthResponse>("/pnl/truth");
}

// ── Auction / overnight-bias (advisory) ───────────────────────────────────────
// GET /auction/bias/{symbol} — engine-derived Saty + TPO + Corey synthesis into a
// line-in-the-sand overnight read. Advisory only; NOT a mirror of the TOS chart.
// Numbers are gated by engine/tests/test_auction_bias_parity.py. See
// engine/routers/auction_bias_router.py and docs/design/es-auction-overnight-bias-card.md.
export interface AuctionBiasProvenance {
  is_live: boolean;
  source: string;
  as_of: number | null;
  stale_after_s: number;
}

export interface AuctionBiasSaty {
  atr: number;
  call_trigger: number;
  put_trigger: number;
  plus_1_atr: number;
  minus_1_atr: number;
  bias: "long" | "short" | "neutral";
  day_range_pct_of_atr: number | null;
}

export interface AuctionBiasSynthesis {
  line_in_sand: number;
  line_source: string;
  long_above: number;
  short_below: number;
  confirm_long_above: number;
  confirm_short_below: number | null;
  lean: string;
  overnight_recommendation: string;
}

// Unavailable shape: the endpoint returns available:false (still HTTP 200) when
// the provider has no usable market data — the card renders STATIC, not an error.
export interface AuctionBiasResponse {
  symbol: string;
  available: boolean;
  error?: string;
  // Present only when available === true:
  price?: number;
  prior_close?: number;
  saty?: AuctionBiasSaty;
  tpo?: Record<string, unknown> | null;
  corey?: Record<string, unknown> | null;
  synthesis?: AuctionBiasSynthesis;
  engine_derived?: boolean;
  chart_parity?: boolean;
  caveats?: string[];
  provenance?: AuctionBiasProvenance;
  // Present only when available === false:
  is_live?: boolean;
  source?: string;
  as_of?: number | null;
  stale_after_s?: number;
}

export async function fetchAuctionBias(symbol: string): Promise<AuctionBiasResponse> {
  return fetchEngine<AuctionBiasResponse>(`/auction/bias/${symbol}`);
}
