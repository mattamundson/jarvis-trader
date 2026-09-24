import type { SpxIntradayMetrics, SpxOperatorVerdict, SpxVerdict } from "./types";

function exists(n: number | null | undefined): n is number {
  return n != null && Number.isFinite(n);
}

function level(metrics: SpxIntradayMetrics, value: number): number {
  return metrics.levels.find((l) => Math.abs(l.value - value) < 0.01)?.value ?? value;
}

function weakMomentum(metrics: SpxIntradayMetrics): boolean {
  const windows = [
    metrics.returns.fiveMinPct,
    metrics.returns.fifteenMinPct,
    metrics.returns.thirtyMinPct,
    metrics.returns.sixtyMinPct,
  ].filter(exists);
  return windows.length > 0 && windows.filter((v) => v < 0).length >= Math.ceil(windows.length / 2);
}

export function buildSpxVerdict(metrics: SpxIntradayMetrics, sourceQuality: "fresh" | "stale" | "degraded"): SpxVerdict {
  const price = metrics.currentPrice;
  if (sourceQuality === "degraded" || price == null) {
    return {
      label: "DATA_DEGRADED",
      confidence: 0,
      summary: "SPX intraday decision panel is degraded because the live price/bars feed is unavailable.",
      bullEvidence: [],
      bearEvidence: ["Live market data unavailable or stale enough to block a confident read"],
      invalidation: ["Refresh data source before using this panel for operator decisions"],
    };
  }

  const immediate = level(metrics, 7752.01);
  const pivot = level(metrics, 7749.78);
  const buyerControl = level(metrics, 7743.84);
  const failure = level(metrics, 7738.02);
  const aboveShortMas = (!exists(metrics.ema9) || price >= metrics.ema9) && (!exists(metrics.ema21) || price >= metrics.ema21);
  const belowShortMas = (exists(metrics.ema9) && price < metrics.ema9) || (exists(metrics.ema21) && price < metrics.ema21);
  const vixSoft = !exists(metrics.vix) || metrics.vix < 18;
  const qqqPositive = !exists(metrics.breadth.qqqPct) || metrics.breadth.qqqPct > 0;
  const momentumWeak = weakMomentum(metrics);
  const bullEvidence: string[] = [];
  const bearEvidence: string[] = [];

  if (vixSoft) bullEvidence.push(`VIX soft${exists(metrics.vix) ? ` at ${metrics.vix.toFixed(2)}` : ""}`);
  if (exists(metrics.vwap) && price > metrics.vwap) bullEvidence.push("SPX/proxy remains above session VWAP");
  if (exists(metrics.breadth.rspPct) && metrics.breadth.rspPct > 0) bullEvidence.push("Equal-weight participation remains positive");
  if (exists(metrics.breadth.iwmPct) && metrics.breadth.iwmPct > 0) bullEvidence.push("IWM is not breaking down");

  if (price < immediate) bearEvidence.push(`${immediate.toFixed(2)} breakout support is lost`);
  if (belowShortMas) bearEvidence.push("Price is below short-term moving averages");
  if (momentumWeak) bearEvidence.push("5/15/30/60 minute momentum mix is weak");
  if (exists(metrics.breadth.qqqPct) && exists(metrics.breadth.iwmPct) && metrics.breadth.qqqPct - metrics.breadth.iwmPct > 0.7) {
    bearEvidence.push("Leadership is narrow: QQQ materially ahead of IWM");
  }

  let label: SpxOperatorVerdict = "PIN_CHOP";
  let confidence = 0.55;
  let summary = `SPX is balanced around the ${pivot.toFixed(2)} pivot; expect chop until ${immediate.toFixed(2)} is reclaimed or ${buyerControl.toFixed(2)} breaks.`;

  if (price < failure) {
    label = "REVERSAL_CONFIRMED";
    confidence = 0.82;
    summary = `SPX is below ${failure.toFixed(2)}; bullish intraday thesis has failed and reversal risk dominates.`;
  } else if (price < buyerControl) {
    label = "REVERSAL_CONFIRMED";
    confidence = 0.72;
    summary = `SPX lost buyer control at ${buyerControl.toFixed(2)}; reversal risk is dominant unless price rapidly reclaims ${pivot.toFixed(2)}.`;
  } else if (price < immediate && (price <= pivot + 1.5 || momentumWeak || belowShortMas)) {
    label = "BREAKOUT_FAILURE_TEST";
    confidence = 0.68;
    summary = `SPX lost ${immediate.toFixed(2)} and is testing the ${pivot.toFixed(2)} breakout shelf; ${buyerControl.toFixed(2)} is the downside magnet unless ${immediate.toFixed(2)} is reclaimed.`;
  } else if (price > immediate && aboveShortMas && vixSoft && qqqPositive && !momentumWeak) {
    label = "CONTINUATION";
    confidence = 0.66;
    summary = `SPX is above ${immediate.toFixed(2)} with supportive volatility; continuation/high-level hold is favored while that level holds.`;
  }

  if (sourceQuality === "stale") {
    confidence = Math.min(confidence, 0.45);
    bearEvidence.push("Data freshness is stale; confidence is capped");
  }

  return {
    label,
    confidence,
    summary,
    bullEvidence,
    bearEvidence,
    invalidation: [
      `Bullish save/reclaim requires sustained trade above ${immediate.toFixed(2)}`,
      `Breakout-failure confirmation below ${pivot.toFixed(2)}`,
      `Reversal confirmation below ${buyerControl.toFixed(2)} then ${failure.toFixed(2)}`,
    ],
  };
}
