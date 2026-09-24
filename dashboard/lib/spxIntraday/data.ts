import type { IntradayBar, MarketPriceSnapshot, SpxIntradayInputs, SpxProxyUsed } from "./types";

const PRICE_SYMBOLS = [
  "^GSPC",
  "SPY",
  "QQQ",
  "RSP",
  "IWM",
  "^VIX",
  "VIX",
  "XLK",
  "XLY",
  "XLF",
  "XLC",
  "XLRE",
  "XLI",
  "XLU",
  "XLV",
  "XLP",
  "XLE",
  "XLB",
];

type RawBar = {
  time?: string | number;
  timestamp?: string | number;
  open?: string | number;
  high?: string | number;
  low?: string | number;
  close?: string | number;
  volume?: string | number | null;
  vwap?: string | number | null;
};

function toNumber(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function normalizeBars(raw: unknown): IntradayBar[] {
  const arr = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as { bars?: RawBar[] })?.bars)
      ? ((raw as { bars?: RawBar[] }).bars as RawBar[])
      : [];
  return arr
    .map((bar): IntradayBar | null => {
      const b = bar as RawBar;
      const rawTime = b.time ?? b.timestamp;
      const time = typeof rawTime === "string" ? Math.floor(new Date(rawTime).getTime() / 1000) : Number(rawTime);
      const open = toNumber(b.open);
      const high = toNumber(b.high);
      const low = toNumber(b.low);
      const close = toNumber(b.close);
      if (![time, open, high, low, close].every(Number.isFinite)) return null;
      return {
        time,
        open: open as number,
        high: high as number,
        low: low as number,
        close: close as number,
        volume: toNumber(b.volume) ?? undefined,
        vwap: toNumber(b.vwap) ?? undefined,
      };
    })
    .filter((bar): bar is IntradayBar => bar != null)
    .sort((a, b) => a.time - b.time);
}

async function fetchJson<T>(url: string, warnings: string[]): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      warnings.push(`${url} returned HTTP ${res.status}`);
      return null;
    }
    return (await res.json()) as T;
  } catch (error) {
    warnings.push(`${url} failed: ${error instanceof Error ? error.message : String(error)}`);
    return null;
  }
}

function latestPrice(prices: MarketPriceSnapshot, symbol: string): number | null {
  return toNumber(prices[symbol]?.last_price);
}

function scaleBars(bars: IntradayBar[], scale: number): IntradayBar[] {
  return bars.map((bar) => ({
    ...bar,
    open: bar.open * scale,
    high: bar.high * scale,
    low: bar.low * scale,
    close: bar.close * scale,
    vwap: bar.vwap == null ? undefined : bar.vwap * scale,
  }));
}

async function fetchBars(origin: string, symbol: string, futures: boolean, warnings: string[]): Promise<IntradayBar[]> {
  const qs = `timeframe=1m&days=2&limit=500&futures=${futures}`;
  const raw = await fetchJson<unknown>(`${origin}/api/engine/analyze/bars/${encodeURIComponent(symbol)}?${qs}`, warnings);
  return normalizeBars(raw);
}

export async function fetchSpxIntradayInputs(origin: string): Promise<SpxIntradayInputs> {
  const warnings: string[] = [];
  const priceQuery = encodeURIComponent(PRICE_SYMBOLS.join(","));
  const prices =
    (await fetchJson<MarketPriceSnapshot>(`${origin}/api/engine/prices/snapshot?symbols=${priceQuery}`, warnings)) ?? {};

  let proxyUsed: SpxProxyUsed = "SPX_DIRECT";
  let bars = await fetchBars(origin, "^GSPC", false, warnings);

  if (bars.length === 0) {
    const esBars = await fetchBars(origin, "ES", true, warnings);
    const spx = latestPrice(prices, "^GSPC");
    const es = esBars.at(-1)?.close ?? null;
    if (esBars.length && spx && es) {
      proxyUsed = "ES_ADJUSTED";
      bars = scaleBars(esBars, spx / es);
    }
  }

  if (bars.length === 0) {
    const spyBars = await fetchBars(origin, "SPY", false, warnings);
    const spx = latestPrice(prices, "^GSPC");
    const spy = latestPrice(prices, "SPY") ?? spyBars.at(-1)?.close ?? null;
    const scale = spx && spy ? spx / spy : 10;
    proxyUsed = "SPY_PROXY";
    bars = scaleBars(spyBars, scale);
    if (!spx) warnings.push("Using SPY×10 proxy because direct SPX snapshot was unavailable");
  }

  return {
    asOf: new Date().toISOString(),
    prices,
    bars,
    proxyUsed,
    warnings,
  };
}
