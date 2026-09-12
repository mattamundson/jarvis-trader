import { promises as fs } from "node:fs";
import path from "node:path";

export type ReadinessBadgeKey =
  | "operator_analysis_ready"
  | "monitoring_ready"
  | "execution_ready"
  | "recommendation_attribution_proven"
  | "queue_order_lineage_proven"
  | "edge_certified";

export interface ReadinessScorecard {
  schema_version: "jarvis-readiness-scorecard.v1";
  generated_at: string;
  source_reports: {
    readiness: string;
    attribution: string;
    baseline: string;
  };
  mode: "READ_ONLY_ANALYSIS";
  safety: {
    live_trading_changed: false;
    risk_config_changed: false;
    kill_switch_changed: false;
    broker_execution_changed: false;
    env_changed: false;
  };
  badges: Record<ReadinessBadgeKey, boolean>;
  metrics: {
    dashboard_ok: boolean;
    engine_ok: boolean;
    current_actionable_shown: number | null;
    current_actionable_raw: number | null;
    pending_approvals: number | null;
    unique_linked_paper_trades: number;
    linked_rth_paper_trades: number;
    queue_order_id_matches_to_paper: number;
    linked_closed_pnl: number;
    linked_profit_factor: number;
    rth_linked_closed_pnl: number;
    rth_linked_profit_factor: number;
    linked_vs_unlinked_pnl_delta: number;
    linked_vs_all_paper_avg_trade_delta: number;
  };
  blockers: string[];
  display_notes: string[];
}

type JsonRecord = Record<string, unknown>;

const SOURCE_REPORTS = {
  readiness: "docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.json",
  attribution: "docs/reports/JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json",
  baseline: "docs/reports/JARVIS_RECOMMENDATION_BASELINE_COMPARISON_LATEST.json",
} as const;

function repoRoot(): string {
  const envPath = process.env.JARVIS_REPO_ROOT;
  if (envPath && envPath.trim()) return path.resolve(envPath);
  return path.resolve(process.cwd(), "..");
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asBool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function stringList(value: unknown): string[] {
  return asArray(value).filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function parseReportJson(raw: string): JsonRecord {
  // Python's stdlib JSON writer permits Infinity/NaN by default; JavaScript's
  // JSON.parse correctly rejects them. Normalize non-finite numeric sentinels to
  // null so the read-only dashboard API degrades those optional fields without
  // failing the whole scorecard contract.
  const strictJson = raw.replace(/\b-Infinity\b|\bInfinity\b|\bNaN\b/g, "null");
  return asRecord(JSON.parse(strictJson));
}

async function readJson(reportPath: string): Promise<JsonRecord> {
  const fullPath = path.resolve(repoRoot(), reportPath);
  const raw = await fs.readFile(fullPath, "utf8");
  return parseReportJson(raw);
}

export async function buildReadinessScorecard(): Promise<ReadinessScorecard> {
  const [readiness, attribution, baseline] = await Promise.all([
    readJson(SOURCE_REPORTS.readiness),
    readJson(SOURCE_REPORTS.attribution),
    readJson(SOURCE_REPORTS.baseline),
  ]);

  const readinessVerdict = asRecord(readiness.verdict);
  const currentRecommendations = asRecord(readinessVerdict.current_recommendations);
  const historicalPerformance = asRecord(readinessVerdict.historical_performance);
  const attributionSummary = asRecord(attribution.summary);
  const attributionStats = asRecord(attribution.stats);
  const attributionVerdict = asRecord(attribution.verdict);
  const baselineComparisons = asRecord(baseline.comparisons);
  const linkedVsUnlinked = asRecord(baselineComparisons.linked_vs_unlinked);
  const linkedVsAllPaper = asRecord(baselineComparisons.linked_vs_all_paper);
  const baselineVerdict = asRecord(baseline.verdict);
  const baselineSafety = asRecord(baseline.safety);
  const allUniqueLinked = asRecord(attributionStats.all_unique_linked);
  const rthLinked = asRecord(attributionStats.rth_linked);

  const generatedAt = asString(
    baseline.generated_at,
    asString(attribution.generated_at, asString(readiness.generated_at, new Date().toISOString()))
  );

  return {
    schema_version: "jarvis-readiness-scorecard.v1",
    generated_at: generatedAt,
    source_reports: SOURCE_REPORTS,
    mode: "READ_ONLY_ANALYSIS",
    safety: {
      live_trading_changed: false,
      risk_config_changed: false,
      kill_switch_changed: false,
      broker_execution_changed: false,
      env_changed: false,
    },
    badges: {
      operator_analysis_ready: asBool(readinessVerdict.operator_analysis_ready),
      monitoring_ready: asBool(readinessVerdict.monitoring_ready),
      execution_ready: asBool(readinessVerdict.execution_ready),
      recommendation_attribution_proven: asBool(attributionVerdict.recommendation_attribution_proven),
      queue_order_lineage_proven:
        asBool(attributionVerdict.queue_order_id_attribution_proven) ||
        asBool(baselineVerdict.queue_order_lineage_proven),
      edge_certified: asBool(baselineVerdict.edge_certified),
    },
    metrics: {
      dashboard_ok: asBool(readinessVerdict.dashboard_ok),
      engine_ok: asBool(readinessVerdict.engine_ok),
      current_actionable_shown: asNullableNumber(currentRecommendations.shown),
      current_actionable_raw: asNullableNumber(currentRecommendations.raw),
      pending_approvals: asNullableNumber(currentRecommendations.pending_approvals),
      unique_linked_paper_trades: asNumber(attributionSummary.unique_linked_paper_trades),
      linked_rth_paper_trades: asNumber(attributionSummary.linked_rth_paper_trades),
      queue_order_id_matches_to_paper: asNumber(attributionSummary.queue_order_id_matches_to_paper),
      linked_closed_pnl: asNumber(allUniqueLinked.pnl, asNumber(historicalPerformance.linked_closed_pnl)),
      linked_profit_factor: asNumber(allUniqueLinked.profit_factor, asNumber(historicalPerformance.linked_profit_factor)),
      rth_linked_closed_pnl: asNumber(rthLinked.pnl),
      rth_linked_profit_factor: asNumber(rthLinked.profit_factor),
      linked_vs_unlinked_pnl_delta: asNumber(linkedVsUnlinked.pnl_delta),
      linked_vs_all_paper_avg_trade_delta: asNumber(linkedVsAllPaper.avg_trade_delta),
    },
    blockers: stringList(readinessVerdict.blockers),
    display_notes: [
      "Analysis-ready does not mean execution-ready.",
      "Queue order-id lineage remains unproven until order_id joins paper_trades.trade_id/idempotency_key.",
      "No live trading, risk, kill-switch, broker execution, or symbol gate changes are represented by this scorecard.",
      asBool(baselineVerdict.edge_certified)
        ? "Baseline comparison has certified edge under the current report contract."
        : "Baseline comparison is favorable for linked trades, but edge_certified=false until lineage and forward baseline are proven.",
    ],
  };
}

export function assertReadOnlyScorecardSafety(scorecard: ReadinessScorecard): void {
  if (scorecard.mode !== "READ_ONLY_ANALYSIS") {
    throw new Error(`Unexpected scorecard mode: ${scorecard.mode}`);
  }
  for (const [key, value] of Object.entries(scorecard.safety)) {
    if (value !== false) throw new Error(`Safety flag must remain false: ${key}`);
  }
}
