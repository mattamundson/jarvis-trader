import { NextResponse } from "next/server";
import { assertReadOnlyScorecardSafety, buildReadinessScorecard } from "@/lib/readinessScorecard";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const scorecard = await buildReadinessScorecard();
    assertReadOnlyScorecardSafety(scorecard);
    return NextResponse.json(scorecard, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (error) {
    return NextResponse.json(
      {
        schema_version: "jarvis-readiness-scorecard.v1",
        mode: "READ_ONLY_ANALYSIS",
        error: error instanceof Error ? error.message : "Unknown readiness scorecard error",
        safety: {
          live_trading_changed: false,
          risk_config_changed: false,
          kill_switch_changed: false,
          broker_execution_changed: false,
          env_changed: false,
        },
        badges: {
          operator_analysis_ready: false,
          monitoring_ready: false,
          execution_ready: false,
          recommendation_attribution_proven: false,
          queue_order_lineage_proven: false,
          edge_certified: false,
        },
        blockers: ["readiness_scorecard_api_degraded"],
      },
      { status: 200, headers: { "Cache-Control": "no-store, max-age=0" } }
    );
  }
}
