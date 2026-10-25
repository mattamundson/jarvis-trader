import type { MarketBriefSnapshot, MarketBriefSymbolSnapshot } from "./types";

interface Bar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

const SYMBOLS = ["SPY", "QQQ", "^VIX", "ES=F", "NQ=F"] as const;
const MODEL_VERSION = "market-brief-public-live-v1";
// Upstream Yahoo bars are cached in Next's data cache so a public request does not
// hammer the upstream provider or add multi-second latency to every page view.
const YAHOO_REVALIDATE_SECONDS = 300;
const WALKFORWARD_VERDICT = {
  n: 1197,
  mean_brier_model: 0.594619,
  mean_brier_base: 0.596765,
  paired_diff_base_minus_model: 0.002146,
  paired_ci95: [-0.002225, 0.006517] as [number, number],
  paired_t: 0.962,
  model_beats_base: false,
  verdict: "state conditioning has no measurable edge over the trailing base rate",
};

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isoDateFromUnix(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

async function fetchYahooDaily(symbol: string, range = "5y"): Promise<Bar[]> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${encodeURIComponent(range)}&interval=1d&includePrePost=false`;
  const response = await fetch(url, {
    next: { revalidate: YAHOO_REVALIDATE_SECONDS },
    headers: { "User-Agent": "Mozilla/5.0 jarvis-public-market-brief" },
  });
  if (!response.ok) throw new Error(`Yahoo daily ${symbol} HTTP ${response.status}`);
  const payload = await response.json() as {
    chart?: { result?: Array<{ timestamp?: number[]; indicators?: { quote?: Array<Record<string, Array<number | null>>> } }> };
  };
  const node = payload.chart?.result?.[0];
  const timestamps = node?.timestamp ?? [];
  const quote = node?.indicators?.quote?.[0] ?? {};
  const opens = quote.open ?? [];
  const highs = quote.high ?? [];
  const lows = quote.low ?? [];
  const closes = quote.close ?? [];
  const bars: Bar[] = [];
  for (let i = 0; i < timestamps.length; i += 1) {
    const open = finite(opens[i]);
    const high = finite(highs[i]);
    const low = finite(lows[i]);
    const close = finite(closes[i]);
    if (open == null || high == null || low == null || close == null) continue;
    bars.push({ date: isoDateFromUnix(timestamps[i]), open, high, low, close });
  }
  if (bars.length < 2) throw new Error(`Yahoo daily ${symbol} returned too few bars (${bars.length})`);
  return bars;
}

function pivotSnapshot(bars: Bar[]): MarketBriefSymbolSnapshot {
  const last = bars[bars.length - 1];
  const prev = bars[bars.length - 2];
  const basis = prev ?? last;
  const pivot = (basis.high + basis.low + basis.close) / 3;
  const r1 = 2 * pivot - basis.low;
  const s1 = 2 * pivot - basis.high;
  return {
    provider: "yahoo-live",
    confidence: 0.8,
    gap_pct: prev ? Number((100 * (last.close - prev.close) / prev.close).toFixed(4)) : null,
    daily: {
      prev_close: prev?.close ?? null,
      last_close: last.close,
      day_open: last.open,
      day_high: last.high,
      day_low: last.low,
      prev_day_high: prev?.high ?? null,
      prev_day_low: prev?.low ?? null,
    },
    pivots: {
      pivot,
      r1,
      s1,
      support_2: pivot - (basis.high - basis.low),
      resistance_2: pivot + (basis.high - basis.low),
    },
  };
}

function classifyState(isAthClose: boolean, vix: number | undefined, accel5: number | null): string {
  if (!isAthClose) return "not_ath_close";
  const lowVol = vix != null && vix < 16;
  if (accel5 == null) return lowVol ? "ath_close_lowvol_unknown" : "ath_close_hivol";
  if (lowVol && accel5 > 2) return "ath_close_lowvol_accel_gt2";
  if (lowVol && accel5 >= 0 && accel5 <= 2) return "ath_close_lowvol_accel_0to2";
  if (lowVol) return "ath_close_lowvol_other";
  return "ath_close_hivol";
}

function labelPartition(nextClose: number, nextLow: number, signalClose: number, signalLow: number): "continuation" | "rotation" | "failure" {
  if (nextClose > signalClose) return "continuation";
  if (nextLow < signalLow) return "failure";
  return "rotation";
}

function exactRates(counts: Record<"continuation" | "rotation" | "failure", number>, n: number) {
  const keys = ["continuation", "rotation", "failure"] as const;
  if (n <= 0) return { continuation: 0, rotation: 0, failure: 0, sum: 0 };
  const exact = Object.fromEntries(keys.map((key) => [key, 1000 * counts[key] / n])) as Record<typeof keys[number], number>;
  const base = Object.fromEntries(keys.map((key) => [key, Math.floor(exact[key])])) as Record<typeof keys[number], number>;
  let residual = Math.round(1000 - keys.reduce((acc, key) => acc + base[key], 0));
  const order = [...keys].sort((a, b) => (exact[b] - base[b]) - (exact[a] - base[a]));
  let i = 0;
  while (residual > 0) {
    base[order[i % order.length]] += 1;
    residual -= 1;
    i += 1;
  }
  const continuation = Number((base.continuation / 10).toFixed(1));
  const rotation = Number((base.rotation / 10).toFixed(1));
  const failure = Number((base.failure / 10).toFixed(1));
  return { continuation, rotation, failure, sum: Number((continuation + rotation + failure).toFixed(1)) };
}

function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function buildRecords(es: Bar[], vixByDate: Record<string, number>) {
  let runMaxClose = -Infinity;
  return es.map((bar, i) => {
    const accel5 = i < 5 ? null : 100 * (bar.close - es[i - 5].close) / es[i - 5].close;
    const isAthClose = bar.close > runMaxClose;
    runMaxClose = Math.max(runMaxClose, bar.close);
    return {
      i,
      date: bar.date,
      open: bar.open,
      low: bar.low,
      close: bar.close,
      is_ath_close: isAthClose,
      accel5,
      vix: vixByDate[bar.date],
      state: classifyState(isAthClose, vixByDate[bar.date], accel5),
    };
  });
}

function summarizeRows(rows: ReturnType<typeof buildRecords>, es: Bar[]) {
  const usable = rows.filter((row) => row.i + 5 < es.length);
  const counts = { continuation: 0, rotation: 0, failure: 0 };
  let higherHigh = 0;
  let gapDown = 0;
  let up5 = 0;
  let belowSignalLow = 0;
  const d5s: number[] = [];
  const mae5s: number[] = [];
  for (const row of usable) {
    const i = row.i;
    const next = es[i + 1];
    const label = labelPartition(next.close, next.low, row.close, row.low);
    counts[label] += 1;
    if (next.high > es[i].high) higherHigh += 1;
    if (next.low < row.low) belowSignalLow += 1;
    if (next.open < row.open) gapDown += 1;
    const c5 = es[i + 5].close;
    d5s.push(100 * (c5 - row.close) / row.close);
    if (c5 > row.close) up5 += 1;
    mae5s.push(100 * (Math.min(...es.slice(i + 1, i + 6).map((bar) => bar.low)) - row.close) / row.close);
  }
  const n = usable.length;
  const rates = exactRates(counts, n);
  return {
    n,
    ...rates,
    p_higher_high: n ? Number((100 * higherHigh / n).toFixed(1)) : 0,
    p_gap_down: n ? Number((100 * gapDown / n).toFixed(1)) : 0,
    p_up_5d: n ? Number((100 * up5 / n).toFixed(1)) : 0,
    median_5d: Number(median(d5s).toFixed(2)),
    median_mae5: Number(median(mae5s).toFixed(2)),
    p_below_signal_low: n ? Number((100 * belowSignalLow / n).toFixed(1)) : 0,
  };
}

async function liveBaseRate() {
  const [es, vix] = await Promise.all([fetchYahooDaily("ES=F", "5y"), fetchYahooDaily("^VIX", "5y")]);
  const vixByDate = Object.fromEntries(vix.map((bar) => [bar.date, bar.close]));
  const records = buildRecords(es, vixByDate);
  const all = summarizeRows(records, es);
  const today = records[records.length - 1];
  const matchedRows = records.filter((row) => row.state === today.state);
  const matched = summarizeRows(matchedRows, es);
  return { es, today, all, matched };
}

export async function loadLivePublicMarketBrief(nowMs = Date.now()): Promise<MarketBriefSnapshot> {
  const generatedAt = new Date(nowMs).toISOString();
  const [snapshots, base] = await Promise.all([
    Promise.all(SYMBOLS.map(async (symbol) => [symbol, pivotSnapshot(await fetchYahooDaily(symbol, "1mo"))] as const)),
    liveBaseRate(),
  ]);
  const symbols = Object.fromEntries(snapshots) as Record<string, MarketBriefSymbolSnapshot>;
  const probs = {
    continuation: base.all.continuation,
    rotation: base.all.rotation,
    failure: base.all.failure,
  };
  return {
    mode: "ANALYSIS_ONLY",
    orders_enabled: false,
    risk_config_touched: false,
    asOf: generatedAt,
    generatedAt,
    sourcePath: null,
    sourceQuality: "fresh",
    ageSeconds: 0,
    scores: {
      status: "computed",
      macro_event_count: 0,
      probabilities: probs,
      probability_source: {
        primary: "trailing_unconditional_base_rate",
        conditional_status: "provisional_no_measured_edge",
        rationale: "Live public brief uses the measured trailing unconditional ES base rate; state conditioning remains diagnostic only.",
        walkforward: WALKFORWARD_VERDICT,
      },
      conditional_diagnostic: {
        state: base.today.state,
        n: base.matched.n,
        status: "provisional_no_measured_edge",
        publish_as_edge: false,
        probabilities: {
          continuation: base.matched.continuation,
          rotation: base.matched.rotation,
          failure: base.matched.failure,
          sum: base.matched.sum,
        },
      },
      notes: [
        "Live public generator: Yahoo daily data, floor-trader pivots, measured ES base rates.",
        "No broker, order routing, account state, risk config, or kill-switch access.",
      ],
      macro_events: [],
    },
    symbols,
    levels: ["ES=F", "NQ=F", "SPY", "QQQ"].map((symbol) => ({
      symbol,
      pivot: symbols[symbol]?.pivots?.pivot ?? null,
      r1: symbols[symbol]?.pivots?.r1 ?? null,
      s1: symbols[symbol]?.pivots?.s1 ?? null,
    })),
    warnings: [
      "Live public brief uses exchange/daily Yahoo bars; intraday premarket microstructure is a follow-up data layer.",
    ],
    modelVersion: MODEL_VERSION,
  };
}

export const __test__ = { exactRates, labelPartition, classifyState };
