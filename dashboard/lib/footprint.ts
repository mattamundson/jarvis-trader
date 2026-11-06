import type { Bar1m } from "./flowTypes";

export interface FootprintLevel {
  price: number;
  bidLots: number;
  askLots: number;
  delta: number;
  totalVolume: number;
}

export interface FootprintBar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  levels: FootprintLevel[];
  totalVolume: number;
  netDelta: number;
}

export interface VolumeProfileLevel {
  price: number;
  volume: number;
  bidVolume: number;
  askVolume: number;
}

export interface CompositeProfile {
  levels: VolumeProfileLevel[];
  poc: number;
  valueAreaHigh: number;
  valueAreaLow: number;
  totalVolume: number;
}

export function buildFootprintBar(bar: Bar1m): FootprintBar {
  const levels: FootprintLevel[] = [];
  const bidAtPrice = bar.bidAtPrice || {};
  const askAtPrice = bar.askAtPrice || {};

  const allPrices = new Set([
    ...Object.keys(bidAtPrice).map(Number),
    ...Object.keys(askAtPrice).map(Number),
  ]);

  allPrices.forEach((price) => {
    const bidLots = bidAtPrice[price] || 0;
    const askLots = askAtPrice[price] || 0;
    const delta = bidLots - askLots;
    const totalVolume = bidLots + askLots;

    levels.push({
      price,
      bidLots,
      askLots,
      delta,
      totalVolume,
    });
  });

  levels.sort((a, b) => b.price - a.price);

  const totalVolume = levels.reduce((sum, l) => sum + l.totalVolume, 0);
  const netDelta = levels.reduce((sum, l) => sum + l.delta, 0);

  return {
    ts: bar.ts,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    levels,
    totalVolume,
    netDelta,
  };
}

export function buildCompositeProfile(bars: Bar1m[]): CompositeProfile {
  const priceVolumeMap = new Map<number, { total: number; bid: number; ask: number }>();

  bars.forEach((bar) => {
    const bidAtPrice = bar.bidAtPrice || {};
    const askAtPrice = bar.askAtPrice || {};

    const allPrices = new Set([
      ...Object.keys(bidAtPrice).map(Number),
      ...Object.keys(askAtPrice).map(Number),
    ]);

    allPrices.forEach((price) => {
      const bidVol = bidAtPrice[price] || 0;
      const askVol = askAtPrice[price] || 0;
      const existing = priceVolumeMap.get(price) || { total: 0, bid: 0, ask: 0 };

      priceVolumeMap.set(price, {
        total: existing.total + bidVol + askVol,
        bid: existing.bid + bidVol,
        ask: existing.ask + askVol,
      });
    });
  });

  const levels: VolumeProfileLevel[] = Array.from(priceVolumeMap.entries())
    .map(([price, vol]) => ({
      price,
      volume: vol.total,
      bidVolume: vol.bid,
      askVolume: vol.ask,
    }))
    .sort((a, b) => b.price - a.price);

  const totalVolume = levels.reduce((sum, l) => sum + l.volume, 0);

  const poc =
    levels.length > 0
      ? levels.reduce((max, l) => (l.volume > max.volume ? l : max), levels[0]).price
      : 0;

  const valueAreaVolume = totalVolume * 0.7;
  let accumulatedVolume = 0;
  const valueAreaPrices: number[] = [];

  const sortedByVolume = [...levels].sort((a, b) => b.volume - a.volume);

  for (const level of sortedByVolume) {
    if (accumulatedVolume >= valueAreaVolume) break;
    valueAreaPrices.push(level.price);
    accumulatedVolume += level.volume;
  }

  const valueAreaHigh = valueAreaPrices.length > 0 ? Math.max(...valueAreaPrices) : 0;
  const valueAreaLow = valueAreaPrices.length > 0 ? Math.min(...valueAreaPrices) : 0;

  return {
    levels,
    poc,
    valueAreaHigh,
    valueAreaLow,
    totalVolume,
  };
}

export function aggregateBarsTo5m(bars1m: Bar1m[]): Bar1m[] {
  const bars5m: Bar1m[] = [];

  for (let i = 0; i < bars1m.length; i += 5) {
    const chunk = bars1m.slice(i, i + 5);
    if (chunk.length === 0) continue;

    const open = chunk[0].open;
    const close = chunk[chunk.length - 1].close;
    const high = Math.max(...chunk.map((b) => b.high));
    const low = Math.min(...chunk.map((b) => b.low));
    const volume = chunk.reduce((sum, b) => sum + b.volume, 0);

    const bidAtPrice: Record<number, number> = {};
    const askAtPrice: Record<number, number> = {};

    chunk.forEach((bar) => {
      if (bar.bidAtPrice) {
        Object.entries(bar.bidAtPrice).forEach(([price, lots]) => {
          const p = Number(price);
          bidAtPrice[p] = (bidAtPrice[p] || 0) + lots;
        });
      }
      if (bar.askAtPrice) {
        Object.entries(bar.askAtPrice).forEach(([price, lots]) => {
          const p = Number(price);
          askAtPrice[p] = (askAtPrice[p] || 0) + lots;
        });
      }
    });

    bars5m.push({
      ts: chunk[0].ts,
      open,
      high,
      low,
      close,
      volume,
      bidAtPrice: Object.keys(bidAtPrice).length > 0 ? bidAtPrice : undefined,
      askAtPrice: Object.keys(askAtPrice).length > 0 ? askAtPrice : undefined,
    });
  }

  return bars5m;
}
