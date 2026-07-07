/**
 * Symbol-class routing — the single source of truth for "which chart engine".
 *
 * TradingView's free embed widget serves CME futures on a 15–30 min DELAY, so we
 * never render futures through it. Futures are charted from our OWN engine bars
 * (real-time-capable via `/analyze/bars` + the `price_update` WS tick). Everything
 * else (equities, indices, crypto, macro) is fine on TradingView's hosted data.
 *
 *   chartClassFor("MES")  -> "futures"  (our Lightweight-Charts + our bars)
 *   chartClassFor("SPY")  -> "tv"       (TradingView embed)
 */

export type ChartClass = "futures" | "tv";

/** Front-month micro futures JARVIS trades and charts from its own bars. */
const FUTURES_ROOTS = new Set(["MES", "MGC", "MCL", "MNQ", "M2K"]);

/**
 * Classify a symbol. Handles bare roots ("MES"), continuous tickers
 * ("CME_MINI:MES1!", "MESU2026"), and the digit-bearing M2K root.
 */
export function chartClassFor(symbol: string | null | undefined): ChartClass {
  const s = (symbol ?? "").trim().toUpperCase();
  if (!s) return "tv";
  if (FUTURES_ROOTS.has(s)) return "futures";

  // Strip an exchange prefix ("CME_MINI:MES1!" -> "MES1!").
  const ticker = s.includes(":") ? (s.split(":").pop() ?? s) : s;

  // M2K has a digit in its root, so match it before the digit-stripping path.
  if (ticker.startsWith("M2K")) return "futures";

  // "MES1!" / "MESU2026" -> "MES"
  const root = ticker.replace(/[0-9!].*$/, "");
  if (FUTURES_ROOTS.has(root)) return "futures";

  return "tv";
}

export function isFuturesSymbol(symbol: string | null | undefined): boolean {
  return chartClassFor(symbol) === "futures";
}

/** Internal symbol → TradingView ticker. Bare tickers (e.g. "TSLA") pass through. */
const TV_TICKER: Record<string, string> = {
  // futures (only used by the context map / explicit opt-in — NOT the default path)
  MES: "CME_MINI:MES1!",
  MNQ: "CME_MINI:MNQ1!",
  MGC: "COMEX:MGC1!",
  MCL: "NYMEX:MCL1!",
  M2K: "CME_MINI:M2K1!",
  ES: "CME_MINI:ES1!",
  NQ: "CME_MINI:NQ1!",
  // equities / indices / macro / crypto — TradingView data is appropriate here
  SPY: "AMEX:SPY",
  QQQ: "NASDAQ:QQQ",
  IWM: "AMEX:IWM",
  DIA: "AMEX:DIA",
  VIX: "CBOE:VIX",
  DXY: "TVC:DXY",
  TLT: "NASDAQ:TLT",
  GLD: "AMEX:GLD",
  USO: "AMEX:USO",
  BTC: "BINANCE:BTCUSDT",
  ETH: "BINANCE:ETHUSDT",
};

/** Resolve a symbol to a TradingView ticker for the embed widget. */
export function tvTickerFor(symbol: string): string {
  const s = (symbol ?? "").trim().toUpperCase();
  return TV_TICKER[s] ?? s;
}

/** Macro/market-context tiles for the "where TradingView makes sense" strip. */
export const MARKET_CONTEXT: Array<{ label: string; tv: string }> = [
  { label: "S&P 500 · SPY", tv: "AMEX:SPY" },
  { label: "Nasdaq 100 · QQQ", tv: "NASDAQ:QQQ" },
  { label: "Volatility · VIX", tv: "CBOE:VIX" },
  { label: "US Dollar · DXY", tv: "TVC:DXY" },
  { label: "Bitcoin · BTCUSD", tv: "BINANCE:BTCUSDT" },
  { label: "10Y Treasuries · TLT", tv: "NASDAQ:TLT" },
];
