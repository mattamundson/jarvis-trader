export interface Bar1m {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface DeltaAtPrice {
  price: number;
  bidLots: number;
  askLots: number;
}

export interface BigPrint {
  ts: string;
  price: number;
  lots: number;
  side: "bid" | "ask";
}

export interface Gate {
  level: number;
  status: "untested" | "testing" | "broken";
  closeCount: number;
}

export interface FlowSnapshot {
  ts: string;
  es: {
    last: number;
    vwap: number;
    onHigh: number;
    onLow: number;
    cvd: number;
    cvdLow: number;
    bars1m: Bar1m[];
    deltaAtPrice: DeltaAtPrice[];
    bigPrints: BigPrint[];
  };
  nq: {
    last: number;
    vwap: number;
  };
  gex: {
    callWall: number;
    putWall: number;
    flip: number;
    pin: number;
    asOf: string;
  };
  gates: Gate[];
}

export function isStale(ts: string, thresholdMs = 60_000): boolean {
  return Date.now() - new Date(ts).getTime() > thresholdMs;
}

export function biasLabel(last: number, vwap: number): string {
  const diff = last - vwap;
  if (Math.abs(diff) < 1) return "NEUTRAL";
  return diff > 0 ? "BULL" : "BEAR";
}
