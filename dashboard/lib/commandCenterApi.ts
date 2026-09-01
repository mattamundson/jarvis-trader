import {
  fetchBars,
  fetchEngine,
  fetchJournalStats,
  fetchStrategyLedger,
  fetchSymbolRegime,
  toggleKillSwitch,
  type JournalTradeStats,
  type LedgerResponse,
  type OHLCVBar,
} from "@/lib/api";
import type { ExecutionPathProbe } from "@/lib/executionPath";

export type { JournalTradeStats, LedgerResponse, OHLCVBar };

export interface CommandCenterHealthData {
  status: string;
  kill_switch_active: boolean;
  uptime_seconds: number;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  paper_trading?: boolean;
  version?: string;
  execution_connected_verified?: boolean | null;
  ib_execution_stale?: boolean | null;
  execution_path?: ExecutionPathProbe | null;
}

export interface CommandCenterSafetyData {
  daily_pnl: number;
  equity_peak: number;
  drawdown_pct: number;
  orders_last_minute: number;
  consecutive_losses?: number;
  kill_switch_active?: boolean;
  daily_limit_pct?: number;
  drawdown_limit_pct?: number;
  orders_per_minute_limit?: number;
}

export interface CommandCenterPosition {
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price?: number;
  unrealized_pnl?: number;
}

export interface CommandCenterPortfolioData {
  total_equity: number;
  daily_pnl: number;
  positions: CommandCenterPosition[];
  cash?: number;
}

export interface CommandCenterDecision {
  timestamp: string;
  symbol: string;
  action: string;
  reason?: string;
  signal?: string;
  regime?: string;
  quantity?: number;
  price?: number;
}

export interface CommandCenterSchedulerJob {
  name: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
}

export interface CommandCenterSchedulerData {
  running: boolean;
  jobs?: CommandCenterSchedulerJob[];
  total_decisions_logged: number;
  last_scan?: string;
  next_scan?: string;
}

export interface CommandCenterMacroData {
  vix?: number;
  vix_regime?: string;
  regime?: string;
  timestamp?: string;
}

export interface CommandCenterPaperStatusRow {
  symbol?: string;
  status?: string;
  authorized?: boolean;
  verdict?: string;
  wfe?: number;
  wfe_label?: string;
  reason?: string;
  cleared_date?: string;
  closed_date?: string;
}

export interface CommandCenterTrade {
  timestamp: string;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  pnl?: number;
  commission?: number;
}

export interface CommandCenterDataIntegritySource {
  source?: string;
  status?: string;
  kind?: string;
  provider?: string | null;
  provider_tier?: string | null;
  last_update?: string;
  latency_sec?: number;
  age_seconds?: number;
  cache_key?: string;
}

export interface CommandCenterDataIntegrityResponse {
  timestamp?: string;
  status?: string;
  stale_after_seconds?: number;
  sources?: CommandCenterDataIntegritySource[];
  count?: number;
  cache_age?: {
    status?: string;
    max_age_seconds?: number | null;
    stale_after_seconds?: number;
    by_source?: Array<{ source?: string; age_seconds?: number; status?: string }>;
  };
  provider_tier?: {
    status?: string;
    active?: string | null;
    primary?: string | null;
    fallbacks?: string[];
    reason?: string | null;
  };
  bar_freshness?: {
    status?: string;
    stale_after_seconds?: number;
    max_lag_seconds?: number | null;
    symbols?: string[];
    timeframes?: string[];
    stale_symbols?: string[];
    unknown_symbols?: string[];
  };
  source_parity?: {
    status?: string;
    window_seconds?: number | null;
    checked_symbols?: string[];
    reference_source?: string | null;
    compared_sources?: string[];
    max_delta_bps?: number | null;
    mismatches?: unknown[];
    missing_sources?: string[];
  };
  trade_enablement?: {
    status?: string;
    blocking_reasons?: string[];
  };
}

export function fetchCommandCenterBars(symbol: string): Promise<OHLCVBar[]> {
  return fetchBars(symbol, { timeframe: "15m", days: 14, futures: true });
}

export function fetchCommandCenterRegime(symbol: string) {
  return fetchSymbolRegime(symbol);
}

export function fetchCommandCenterHealth(): Promise<CommandCenterHealthData> {
  return fetchEngine<CommandCenterHealthData>("/health");
}

export function fetchCommandCenterSafety(): Promise<CommandCenterSafetyData> {
  return fetchEngine<CommandCenterSafetyData>("/safety/status");
}

export function fetchCommandCenterPortfolio(): Promise<CommandCenterPortfolioData> {
  return fetchEngine<CommandCenterPortfolioData>("/portfolio");
}

export function fetchCommandCenterDecisions(): Promise<CommandCenterDecision[]> {
  return fetchEngine<CommandCenterDecision[]>("/decisions/recent?limit=5");
}

export function fetchCommandCenterScheduler(): Promise<CommandCenterSchedulerData> {
  return fetchEngine<CommandCenterSchedulerData>("/scheduler/status");
}

export function fetchCommandCenterMacro(): Promise<CommandCenterMacroData> {
  return fetchEngine<CommandCenterMacroData>("/macro/snapshot");
}

export function fetchCommandCenterPaperStatus(): Promise<Record<string, CommandCenterPaperStatusRow>> {
  return fetchEngine<Record<string, CommandCenterPaperStatusRow>>("/backtest/paper-status");
}

export function fetchCommandCenterStrategyLedger(): Promise<LedgerResponse> {
  return fetchStrategyLedger();
}

export function fetchCommandCenterDataIntegrity(): Promise<CommandCenterDataIntegrityResponse> {
  return fetchEngine<CommandCenterDataIntegrityResponse>("/system/data-integrity");
}

export function fetchCommandCenterTrades(): Promise<CommandCenterTrade[]> {
  return fetchEngine<CommandCenterTrade[]>("/portfolio/history/trades");
}

export function fetchCommandCenterJournalStats(): Promise<JournalTradeStats> {
  return fetchJournalStats(30);
}

export function setCommandCenterKillSwitch(activate: boolean): Promise<unknown> {
  return toggleKillSwitch(
    activate ? "activate" : "deactivate",
    activate ? "Manual kill from command center" : undefined,
  );
}
