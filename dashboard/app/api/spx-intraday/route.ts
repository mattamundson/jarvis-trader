import { NextRequest, NextResponse } from "next/server";
import {
  buildProbabilityBands,
  buildScenarios,
  buildSpxIntradayMetrics,
  buildSpxVerdict,
  fetchSpxIntradayInputs,
  type SourceQuality,
  type SpxIntradaySnapshot,
} from "@/lib/spxIntraday";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MODEL_VERSION = "spx-intraday-dashboard-v1";

function sourceQuality(currentPrice: number | null, bars: { time: number }[]): SourceQuality {
  if (currentPrice == null || bars.length === 0) return "degraded";
  const latestBar = bars.at(-1)?.time;
  if (!latestBar || !Number.isFinite(latestBar)) return "degraded";
  const ageMs = Date.now() - latestBar * 1000;
  if (ageMs > 5 * 60_000) return "degraded";
  if (ageMs > 90_000) return "stale";
  return "fresh";
}

function degradedSnapshot(message: string): SpxIntradaySnapshot {
  return {
    mode: "ANALYSIS_ONLY",
    orders_enabled: false,
    risk_config_touched: false,
    asOf: new Date().toISOString(),
    symbol: "SPX",
    proxyUsed: "SPY_PROXY",
    sourceQuality: "degraded",
    currentPrice: null,
    dayHigh: null,
    dayLow: null,
    dayChangePct: null,
    previousClose: null,
    vix: null,
    vixChangePct: null,
    rsi14: null,
    ema9: null,
    ema21: null,
    sma50: null,
    vwap: null,
    returns: {
      fiveMinPct: null,
      fifteenMinPct: null,
      thirtyMinPct: null,
      sixtyMinPct: null,
    },
    breadth: {
      spyPct: null,
      qqqPct: null,
      rspPct: null,
      iwmPct: null,
      spyRspSpread: null,
      qqqIwmSpread: null,
      sectorsGreen: null,
      sectorsTotal: null,
    },
    levels: [],
    probabilityBands: null,
    scenarios: [],
    verdict: {
      label: "DATA_DEGRADED",
      confidence: 0,
      summary: message,
      bullEvidence: [],
      bearEvidence: [message],
      invalidation: ["Refresh market-data sources before relying on this panel"],
    },
    warnings: [message],
    modelVersion: MODEL_VERSION,
  };
}

export async function GET(request: NextRequest) {
  try {
    const origin = request.nextUrl.origin;
    const inputs = await fetchSpxIntradayInputs(origin);
    const metrics = buildSpxIntradayMetrics(inputs.bars, inputs.prices);
    const quality = sourceQuality(metrics.currentPrice, inputs.bars);
    const probabilityBands = quality === "degraded" ? null : buildProbabilityBands(metrics, inputs.bars);
    const scenarios = quality === "degraded" ? [] : buildScenarios(metrics, probabilityBands);
    const verdict = buildSpxVerdict(metrics, quality);
    const payload: SpxIntradaySnapshot = {
      mode: "ANALYSIS_ONLY",
      orders_enabled: false,
      risk_config_touched: false,
      asOf: inputs.asOf,
      symbol: "SPX",
      proxyUsed: inputs.proxyUsed,
      sourceQuality: quality,
      ...metrics,
      probabilityBands,
      scenarios,
      verdict,
      warnings: inputs.warnings,
      modelVersion: MODEL_VERSION,
    };
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (error) {
    return NextResponse.json(
      degradedSnapshot(error instanceof Error ? error.message : "Unknown SPX intraday analysis error"),
      { status: 200, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
