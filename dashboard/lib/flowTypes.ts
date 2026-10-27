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
  fixture?: boolean;
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

export type GateAction = "BREAK" | "ABSORB" | "NEUTRAL";

export interface GateAnalysis {
  level: number;
  action: GateAction;
  reason: string;
}

export function analyzeGateAction(
  gate: Gate,
  currentPrice: number,
  currentCvd: number,
  cvdLow: number,
  deltaAtPrice: DeltaAtPrice[],
): GateAnalysis {
  const priceAtGate = deltaAtPrice.find((d) => Math.abs(d.price - gate.level) < 0.5);
  const priceBeyondGate = currentPrice > gate.level ? currentPrice - gate.level > 1 : gate.level - currentPrice > 1;
  const cvdNewLow = currentCvd <= cvdLow + 50;
  
  if (priceBeyondGate && cvdNewLow) {
    return {
      level: gate.level,
      action: "BREAK",
      reason: "Price beyond gate + CVD near low",
    };
  }
  
  if (priceAtGate) {
    const totalVolume = priceAtGate.bidLots + priceAtGate.askLots;
    const netDelta = Math.abs(priceAtGate.bidLots - priceAtGate.askLots);
    const isHeavyVolume = totalVolume >= 30;
    const isAggressive = netDelta >= 10;
    const priceHolding = Math.abs(currentPrice - gate.level) < 1;
    
    if (isHeavyVolume && isAggressive && priceHolding) {
      return {
        level: gate.level,
        action: "ABSORB",
        reason: "Heavy aggressive volume at gate, price holding",
      };
    }
  }
  
  return {
    level: gate.level,
    action: "NEUTRAL",
    reason: "No clear signal",
  };
}

export function volumePaceRatio(bars: Bar1m[]): { ratio: number; color: string } {
  if (bars.length < 2) return { ratio: 1.0, color: "text-slate-400" };
  
  const currentVol = bars[bars.length - 1].volume;
  const priorBars = bars.slice(0, -1);
  const avgVol = priorBars.reduce((sum, b) => sum + b.volume, 0) / priorBars.length;
  
  if (avgVol === 0) return { ratio: 1.0, color: "text-slate-400" };
  
  const ratio = currentVol / avgVol;
  
  let color = "text-slate-400";
  if (ratio >= 1.5) color = "text-green-400";
  else if (ratio >= 1.2) color = "text-cyan-400";
  else if (ratio <= 0.7) color = "text-red-400";
  else if (ratio <= 0.85) color = "text-yellow-400";
  
  return { ratio, color };
}
