import type { IntradayBar, MarketPriceSnapshot, SpxDecisionLevel, SpxIntradayMetrics } from "./types";

export const SPX_DECISION_LEVELS = [
  { label: "Day high / upside reclaim", value: 7756.76, role: "target" as const },
  { label: "Immediate breakout support", value: 7752.01, role: "pivot" as const },
  { label: "Last breakout shelf", value: 7749.78, role: "pivot" as const },
  { label: "Buyer-control line", value: 7743.84, role: "support" as const },
  { label: "Bull thesis failure", value: 7738.02, role: "failure" as const },
];

const SECTOR_SYMBOLS = ["XLK", "XLY", "XLF", "XLC", "XLRE", "XLI", "XLU", "XLV", "XLP", "XLE", "XLB"];

function finite(n: unknown): number | null {
  const v = Number(n);
  return Number.isFinite(v) ? v : null;
}

function round(n: number, dp = 2): number {
  const factor = 10 ** dp;
  return Math.round(n * factor) / factor;
}

export function simpleMovingAverage(values: number[], length: number): number | null {
  if (values.length < length || length <= 0) return null;
  const slice = values.slice(-length);
  return slice.reduce((sum, v) => sum + v, 0) / length;
}

export function exponentialMovingAverage(values: number[], length: number): number | null {
  if (values.length < length || length <= 0) return null;
  const alpha = 2 / (length + 1);
  let ema = values.slice(0, length).reduce((sum, v) => sum + v, 0) / length;
  for (const value of values.slice(length)) {
    ema = value * alpha + ema * (1 - alpha);
  }
  return ema;
}

export function rsi(values: number[], length = 14): number | null {
  if (values.length <= length) return null;
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= length; i += 1) {
    const delta = values[i] - values[i - 1];
    if (delta >= 0) gains += delta;
    else losses -= delta;
  }
  let avgGain = gains / length;
  let avgLoss = losses / length;
  for (let i = length + 1; i < values.length; i += 1) {
    const delta = values[i] - values[i - 1];
    avgGain = (avgGain * (length - 1) + Math.max(delta, 0)) / length;
    avgLoss = (avgLoss * (length - 1) + Math.max(-delta, 0)) / length;
  }
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export function vwap(bars: IntradayBar[]): number | null {
  let pv = 0;
  let vol = 0;
  for (const bar of bars) {
    const volume = finite(bar.volume) ?? 1;
    const typical = (bar.high + bar.low + bar.close) / 3;
    pv += typical * volume;
    vol += volume;
  }
  return vol > 0 ? pv / vol : null;
}

function returnPct(values: number[], minutes: number): number | null {
  if (values.length <= minutes) return null;
  const previous = values[values.length - 1 - minutes];
  const last = values[values.length - 1];
  if (!previous) return null;
  return ((last - previous) / previous) * 100;
}

function priceChangePct(entry: MarketPriceSnapshot[string] | undefined): number | null {
  return finite(entry?.change_pct);
}

export function buildDecisionLevels(price: number | null): SpxDecisionLevel[] {
  return SPX_DECISION_LEVELS.map((level) => {
    const distance = price == null ? 0 : price - level.value;
    const abs = Math.abs(distance);
    let status: SpxDecisionLevel["status"] = "at";
    if (price != null) {
      if (abs <= 0.75) status = "at";
      else status = distance > 0 ? "above" : "below";
      if (level.role === "pivot" && distance < -0.75) status = "lost";
      if (level.role === "target" && distance > 0.75) status = "reclaimed";
    }
    return { ...level, distance: round(distance), status };
  });
}

export function buildSpxIntradayMetrics(
  bars: IntradayBar[],
  prices: MarketPriceSnapshot,
): SpxIntradayMetrics {
  const sortedBars = [...bars].sort((a, b) => a.time - b.time).filter((b) => Number.isFinite(b.close));
  const closes = sortedBars.map((b) => b.close);
  const directSpx = finite(prices["^GSPC"]?.last_price);
  const lastClose = closes.at(-1) ?? null;
  const currentPrice = directSpx ?? lastClose;
  const previousClose = finite(prices["^GSPC"]?.prev_close) ?? finite(prices.SPY?.prev_close);
  const dayHigh = sortedBars.length ? Math.max(...sortedBars.map((b) => b.high)) : currentPrice;
  const dayLow = sortedBars.length ? Math.min(...sortedBars.map((b) => b.low)) : currentPrice;
  const dayChangePct = currentPrice != null && previousClose ? ((currentPrice - previousClose) / previousClose) * 100 : null;
  const spyPct = priceChangePct(prices.SPY);
  const qqqPct = priceChangePct(prices.QQQ);
  const rspPct = priceChangePct(prices.RSP);
  const iwmPct = priceChangePct(prices.IWM);
  const sectorChanges = SECTOR_SYMBOLS.map((s) => priceChangePct(prices[s])).filter((v): v is number => v != null);

  return {
    currentPrice: currentPrice == null ? null : round(currentPrice),
    dayHigh: dayHigh == null ? null : round(dayHigh),
    dayLow: dayLow == null ? null : round(dayLow),
    dayChangePct: dayChangePct == null ? null : round(dayChangePct, 3),
    previousClose: previousClose == null ? null : round(previousClose),
    vix: finite(prices["^VIX"]?.last_price) ?? finite(prices.VIX?.last_price),
    vixChangePct: finite(prices["^VIX"]?.change_pct) ?? finite(prices.VIX?.change_pct),
    rsi14: closes.length ? round(rsi(closes) ?? NaN, 1) : null,
    ema9: round(exponentialMovingAverage(closes, 9) ?? NaN),
    ema21: round(exponentialMovingAverage(closes, 21) ?? NaN),
    sma50: round(simpleMovingAverage(closes, 50) ?? NaN),
    vwap: round(vwap(sortedBars) ?? NaN),
    returns: {
      fiveMinPct: round(returnPct(closes, 5) ?? NaN, 3),
      fifteenMinPct: round(returnPct(closes, 15) ?? NaN, 3),
      thirtyMinPct: round(returnPct(closes, 30) ?? NaN, 3),
      sixtyMinPct: round(returnPct(closes, 60) ?? NaN, 3),
    },
    breadth: {
      spyPct,
      qqqPct,
      rspPct,
      iwmPct,
      spyRspSpread: spyPct != null && rspPct != null ? round(spyPct - rspPct, 3) : null,
      qqqIwmSpread: qqqPct != null && iwmPct != null ? round(qqqPct - iwmPct, 3) : null,
      sectorsGreen: sectorChanges.length ? sectorChanges.filter((v) => v > 0).length : null,
      sectorsTotal: sectorChanges.length || null,
    },
    levels: buildDecisionLevels(currentPrice == null ? null : round(currentPrice)),
  };
}
