export interface Bar1m {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** Net aggressor delta for the bar; null/absent = unavailable. */
  delta?: number | null;
  /** Session cumulative delta at bar close; null/absent = unavailable. */
  cvd?: number | null;
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

export type GateStatus = "untested" | "testing" | "broken" | "pending" | "touched" | "confirmed";
export type GateKind = "target" | "trigger" | "support" | "resistance" | "invalid" | "level";

export interface Gate {
  level: number;
  status: GateStatus;
  /** null = unavailable (the real recorder snapshot has no close counts). */
  closeCount: number | null;
  kind?: GateKind;
}

export interface FlowSource {
  src: string;
  asOf: string | null;
  /** es only: when the recorder session behind hi/lo/CVD began. */
  since?: string;
}

/**
 * Public flow payload. Rule: unavailable is `null` (shown as UNAVAILABLE), never 0.
 * Prices, levels and gates only; no dollar amounts or account data.
 */
export interface FlowSnapshot {
  ts: string;
  fixture?: boolean;
  es: {
    last: number;
    vwap: number | null;
    /** Recorder-session high/low (see sources.es.since). */
    onHigh: number | null;
    onLow: number | null;
    cvd: number | null;
    cvdLow: number | null;
    bars1m: Bar1m[];
    deltaAtPrice: DeltaAtPrice[] | null;
    bigPrints: BigPrint[] | null;
  };
  nq: {
    last: number | null;
    vwap: number | null;
  };
  gex: {
    callWall: number | null;
    putWall: number | null;
    flip: number | null;
    pin: number | null;
    asOf: string | null;
  };
  gates: Gate[];
  /** Dotted names of fields that are null because the source does not have them. */
  unavailable?: string[];
  sources?: Partial<Record<"es" | "nq" | "gex" | "gates", FlowSource>>;
}

export const UNAVAILABLE = "UNAVAILABLE";

export function fmtNum(v: number | null | undefined, digits = 2): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : UNAVAILABLE;
}

export function fmtAsOf(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return UNAVAILABLE;
  return d.toLocaleString("en-US", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function isStale(ts: string, thresholdMs = 60_000): boolean {
  const age = Date.now() - new Date(ts).getTime();
  return !Number.isFinite(age) || age < 0 || age > thresholdMs;
}

export function biasLabel(last: number, vwap: number | null): string {
  if (vwap == null || !Number.isFinite(vwap) || !Number.isFinite(last)) return UNAVAILABLE;
  const diff = last - vwap;
  if (Math.abs(diff) < 1) return "NEUTRAL";
  return diff > 0 ? "BULL" : "BEAR";
}

export type GateAction = "BREAK" | "ABSORB" | "NEUTRAL" | "UNAVAILABLE";

export interface GateAnalysis {
  level: number;
  action: GateAction;
  reason: string;
}

export function analyzeGateAction(
  gate: Gate,
  currentPrice: number,
  currentCvd: number | null,
  cvdLow: number | null,
  deltaAtPrice: DeltaAtPrice[] | null,
): GateAnalysis {
  if (!Number.isFinite(currentPrice) || !Number.isFinite(gate.level) ||
      currentCvd == null || cvdLow == null || !Number.isFinite(currentCvd) ||
      !Number.isFinite(cvdLow) || deltaAtPrice == null) {
    return { level: gate.level, action: "UNAVAILABLE", reason: "Required CVD/price/delta evidence unavailable" };
  }
  const priceAtGate = deltaAtPrice?.find((d) => Math.abs(d.price - gate.level) < 0.5);
  const priceBeyondGate = currentPrice > gate.level ? currentPrice - gate.level > 1 : gate.level - currentPrice > 1;
  const cvdNewLow = currentCvd !== null && cvdLow !== null && currentCvd <= cvdLow + 50;
  
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

export function volumePaceRatio(bars: Bar1m[]): { ratio: number; color: string } | null {
  if (bars.length < 2 || bars.some(b => !Number.isFinite(b.volume) || b.volume < 0)) return null;
  
  const currentVol = bars[bars.length - 1].volume;
  const priorBars = bars.slice(0, -1);
  const avgVol = priorBars.reduce((sum, b) => sum + b.volume, 0) / priorBars.length;
  
  if (avgVol === 0) return null;
  
  const ratio = currentVol / avgVol;
  
  let color = "text-slate-400";
  if (ratio >= 1.5) color = "text-green-400";
  else if (ratio >= 1.2) color = "text-cyan-400";
  else if (ratio <= 0.7) color = "text-red-400";
  else if (ratio <= 0.85) color = "text-yellow-400";
  
  return { ratio, color };
}
