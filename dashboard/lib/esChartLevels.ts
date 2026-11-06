import type { OHLCVBar } from "@/lib/api";

export interface ESChartLevels {
  atrLevels: ATRLevels | null;
  initialBalance: InitialBalance | null;
  tpoValueArea: TPOValueArea | null;
  priorTPO: TPOValueArea | null;
  gapFillLevel: number | null;
  sessionVWAP: number | null;
  overnightHighLow: OvernightHighLow | null;
}

export interface ATRLevels {
  priorClose: number;
  atr14: number;
  upperLevel: number;
  lowerLevel: number;
  rangeUsedPct: number;
}

export interface InitialBalance {
  high: number;
  low: number;
  startTime: number;
  endTime: number;
}

export interface TPOValueArea {
  vah: number;
  val: number;
  poc: number;
}

export interface OvernightHighLow {
  high: number;
  low: number;
}

function isRTHBar(timestamp: number): boolean {
  const d = new Date(timestamp * 1000);
  const utcHour = d.getUTCHours();
  const utcMin = d.getUTCMinutes();
  const utcMinutes = utcHour * 60 + utcMin;
  return utcMinutes >= 13 * 60 + 30 && utcMinutes < 20 * 60;
}

function isDayStart(timestamp: number): boolean {
  const d = new Date(timestamp * 1000);
  return d.getUTCHours() === 17 && d.getUTCMinutes() === 0;
}

export function calculateATRLevels(bars: OHLCVBar[], currentHigh: number, currentLow: number): ATRLevels | null {
  if (bars.length < 15) return null;

  const dailyBars = bars.filter((b) => isRTHBar(b.time));
  if (dailyBars.length < 15) return null;

  const ranges: number[] = [];
  let prevClose = dailyBars[0].close;

  for (let i = 1; i < dailyBars.length; i++) {
    const bar = dailyBars[i];
    const tr = Math.max(
      bar.high - bar.low,
      Math.abs(bar.high - prevClose),
      Math.abs(bar.low - prevClose)
    );
    ranges.push(tr);
    prevClose = bar.close;
  }

  if (ranges.length < 14) return null;

  const recent14 = ranges.slice(-14);
  const atr14 = recent14.reduce((sum, val) => sum + val, 0) / 14;

  const priorClose = dailyBars[dailyBars.length - 1].close;
  const upperLevel = priorClose + atr14;
  const lowerLevel = priorClose - atr14;

  const currentRange = currentHigh - currentLow;
  const rangeUsedPct = (currentRange / atr14) * 100;

  return {
    priorClose,
    atr14,
    upperLevel,
    lowerLevel,
    rangeUsedPct: Math.min(rangeUsedPct, 999),
  };
}

export function calculateInitialBalance(bars: OHLCVBar[]): InitialBalance | null {
  const today = bars.filter((b) => {
    const d = new Date(b.time * 1000);
    const nowUTC = new Date();
    return (
      d.getUTCFullYear() === nowUTC.getUTCFullYear() &&
      d.getUTCMonth() === nowUTC.getUTCMonth() &&
      d.getUTCDate() === nowUTC.getUTCDate()
    );
  });

  if (today.length === 0) return null;

  const ibStart = today.find((b) => {
    const d = new Date(b.time * 1000);
    const minutes = d.getUTCHours() * 60 + d.getUTCMinutes();
    return minutes >= 13 * 60 + 30 && minutes < 14 * 60 + 30;
  });

  if (!ibStart) return null;

  const ibBars = today.filter((b) => {
    const d = new Date(b.time * 1000);
    const minutes = d.getUTCHours() * 60 + d.getUTCMinutes();
    return minutes >= 13 * 60 + 30 && minutes < 14 * 60 + 30;
  });

  if (ibBars.length === 0) return null;

  const high = Math.max(...ibBars.map((b) => b.high));
  const low = Math.min(...ibBars.map((b) => b.low));

  return {
    high,
    low,
    startTime: ibBars[0].time,
    endTime: ibBars[ibBars.length - 1].time,
  };
}

export function calculateTPOValueArea(bars: OHLCVBar[]): TPOValueArea | null {
  const rthBars = bars.filter((b) => isRTHBar(b.time));
  if (rthBars.length < 10) return null;

  const priceMap = new Map<number, number>();
  const tickSize = 0.25;

  for (const bar of rthBars) {
    for (let price = bar.low; price <= bar.high; price += tickSize) {
      const rounded = Math.round(price / tickSize) * tickSize;
      priceMap.set(rounded, (priceMap.get(rounded) || 0) + 1);
    }
  }

  const sorted = Array.from(priceMap.entries()).sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0) return null;

  const poc = sorted[0][0];
  const totalVolume = Array.from(priceMap.values()).reduce((sum, v) => sum + v, 0);
  const targetVolume = totalVolume * 0.7;

  let cumulative = 0;
  const valuePrices: number[] = [];

  for (const [price] of sorted) {
    valuePrices.push(price);
    cumulative += priceMap.get(price) || 0;
    if (cumulative >= targetVolume) break;
  }

  if (valuePrices.length === 0) return null;

  const vah = Math.max(...valuePrices);
  const val = Math.min(...valuePrices);

  return { vah, val, poc };
}

export function calculateGapFill(bars: OHLCVBar[]): number | null {
  const dailyBars = bars.filter((b) => isRTHBar(b.time));
  if (dailyBars.length === 0) return null;
  return dailyBars[dailyBars.length - 1].close;
}

export function calculateSessionVWAP(bars: OHLCVBar[]): number | null {
  const todayBars = bars.filter((b) => {
    const d = new Date(b.time * 1000);
    const nowUTC = new Date();
    return (
      d.getUTCFullYear() === nowUTC.getUTCFullYear() &&
      d.getUTCMonth() === nowUTC.getUTCMonth() &&
      d.getUTCDate() === nowUTC.getUTCDate()
    );
  });

  if (todayBars.length === 0) return null;

  let sumPV = 0;
  let sumV = 0;

  for (const bar of todayBars) {
    const typical = (bar.high + bar.low + bar.close) / 3;
    const vol = bar.volume || 1;
    sumPV += typical * vol;
    sumV += vol;
  }

  return sumV > 0 ? sumPV / sumV : null;
}

export function calculateOvernightHighLow(bars: OHLCVBar[]): OvernightHighLow | null {
  const overnightBars = bars.filter((b) => !isRTHBar(b.time));
  if (overnightBars.length === 0) return null;

  const high = Math.max(...overnightBars.map((b) => b.high));
  const low = Math.min(...overnightBars.map((b) => b.low));

  return { high, low };
}

export function calculateAllLevels(bars: OHLCVBar[]): ESChartLevels {
  if (bars.length === 0) {
    return {
      atrLevels: null,
      initialBalance: null,
      tpoValueArea: null,
      priorTPO: null,
      gapFillLevel: null,
      sessionVWAP: null,
      overnightHighLow: null,
    };
  }

  const todayBars = bars.filter((b) => {
    const d = new Date(b.time * 1000);
    const nowUTC = new Date();
    return (
      d.getUTCFullYear() === nowUTC.getUTCFullYear() &&
      d.getUTCMonth() === nowUTC.getUTCMonth() &&
      d.getUTCDate() === nowUTC.getUTCDate()
    );
  });

  const currentHigh = todayBars.length > 0 ? Math.max(...todayBars.map((b) => b.high)) : 0;
  const currentLow = todayBars.length > 0 ? Math.min(...todayBars.map((b) => b.low)) : 0;

  return {
    atrLevels: calculateATRLevels(bars, currentHigh, currentLow),
    initialBalance: calculateInitialBalance(bars),
    tpoValueArea: calculateTPOValueArea(todayBars),
    priorTPO: calculateTPOValueArea(bars.filter((b) => {
      const d = new Date(b.time * 1000);
      const yesterday = new Date();
      yesterday.setUTCDate(yesterday.getUTCDate() - 1);
      return (
        d.getUTCFullYear() === yesterday.getUTCFullYear() &&
        d.getUTCMonth() === yesterday.getUTCMonth() &&
        d.getUTCDate() === yesterday.getUTCDate() &&
        isRTHBar(b.time)
      );
    })),
    gapFillLevel: calculateGapFill(bars),
    sessionVWAP: calculateSessionVWAP(bars),
    overnightHighLow: calculateOvernightHighLow(bars),
  };
}
