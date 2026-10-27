// Allow-list serializer for /api/tape.
//
// Everything that leaves the server for the /tape page is REBUILT here from named, typed fields.
// Unknown keys are dropped (not filtered), so a new field in a state file can never leak by
// accident. Strings containing "$" or P&L wording are rejected centrally, and assertNoPrivateKeys()
// is a second, structural check run by the route and the tests. There is deliberately no import of
// any position / P&L / account module in this tree (enforced by tests/tapeGuard.node.test.ts).
import { ctWallToEpochMs } from "@/lib/tape/time";

type P<T> = (v: unknown) => T | null;
type Rec = Record<string, unknown>;

const isObj = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const PRIVATE_TEXT = /[$]|\bp\s*&\s*l\b|\bpnl\b|\bunrealized\b|\brealized\b|\bbuying power\b|\bnet liq/i;

export const num: P<number> = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const bool: P<boolean> = (v) => (typeof v === "boolean" ? v : null);
export const str = (max = 240): P<string> => (v) =>
  typeof v === "string" && !PRIVATE_TEXT.test(v) ? v.slice(0, max) : null;
export const oneOf = <T extends string>(...opts: T[]): P<T> => (v) =>
  typeof v === "string" && (opts as string[]).includes(v) ? (v as T) : null;
export const arr = <T,>(p: P<T>, max: number): P<T[]> => (v) =>
  Array.isArray(v) ? v.slice(-max).map(p).filter((x): x is T => x !== null) : null;
export function shape<S extends Record<string, P<unknown>>>(s: S): P<{ [K in keyof S]: ReturnType<S[K]> }> {
  return (v) => {
    if (!isObj(v)) return null;
    const out: Rec = {};
    for (const k of Object.keys(s)) out[k] = s[k](v[k]);
    return out as { [K in keyof S]: ReturnType<S[K]> };
  };
}

// ---------------------------------------------------------------------------------------------
const nqRel = shape({ nq_pct: num, es_pct: num, rs: num });

export const flowShape = shape({
  as_of_epoch: num,
  interval_s: num,
  session: shape({ trading_day: str(12), since_ct: str(40), trades: num, lots: num }),
  recorder: shape({ state: str(40), heartbeat_age_s: num, last_tick_age_s: num, reconnects: num }),
  basis: shape({ label: oneOf("bid/ask", "tick-rule"), bidask_pct: num }),
  price: shape({ last: num, bid: num, ask: num, vwap: num, hi: num, lo: num }),
  cvd: shape({ value: num, since_ct: str(40) }),
  gate_cvd: shape({
    level: num, cvd: num, side: oneOf("above", "below", "at"), dist: num,
    last_cross_t: num, last_cross_ct: str(10), label: str(40), note: str(200),
  }),
  series_1m: arr(shape({ t: num, o: num, h: num, l: num, c: num, vol: num, delta: num, cvd: num }), 360),
  legs: arr(
    shape({
      n: num, dir: oneOf("up", "down"), t0: num, t1: num, px0: num, px1: num, pts: num,
      minutes: num, vol: num, delta: num, lpm: num, cvd0: num, cvd1: num, open: bool,
    }),
    14,
  ),
  lots_per_min: shape({ last: num, avg5: num, avg30: num, peak: num }),
  levels: arr(
    shape({
      name: str(60), px: num, kind: str(20), dir: oneOf("above", "below"),
      bias: oneOf("bull", "bear", "neutral"), note: str(120),
      status: oneOf("confirmed", "touched", "pending"), price_vs: oneOf("above", "below", "at"), dist: num,
    }),
    24,
  ),
  trigger: shape({
    px: num, dir: oneOf("above", "below"), label: str(80), tf_min: num,
    state: oneOf("confirmed", "pressing", "pending"), last_5m_close: num,
  }),
  bias: shape({
    label: oneOf("BULL", "BEAR", "MIXED"),
    votes: arr(shape({ name: str(30), up: bool }), 6),
    rule: str(120),
  }),
  nq: shape({
    status: oneOf("ok", "down", "off"),
    rel: shape({
      last: num,
      windows: shape({ "30m": nqRel, "60m": nqRel, session: nqRel }),
      lead: str(30),
      gate: shape({ level: num, side: oneOf("above", "below", "at") }),
    }),
    series: arr(shape({ t: num, c: num }), 360),
    as_of_epoch: num,
    interval_s: num,
  }),
});
export type FlowOut = NonNullable<ReturnType<typeof flowShape>>;

export const gexShape = shape({
  asof_ct: str(20), spot: num, call_wall: num, put_wall: num, flip: num, max_pain: num, pin: num,
  net_gex: str(20), source: str(80), flip_vel_pts_hr: num, flip_vel_since: str(10),
  history_today: arr(shape({ asof_ct: str(20), flip: num, pin: num, put_wall: num }), 12),
});
export type GexOut = NonNullable<ReturnType<typeof gexShape>>;

export const levelSourceShape = shape({
  as_of_ct: str(20), source: str(100), note: str(200), seed: bool, interval_s: num,
  levels: arr(shape({ name: str(60), px: num, px2: num, note: str(120) }), 24),
});
export type LevelSourceOut = NonNullable<ReturnType<typeof levelSourceShape>>;

// ---------------------------------------------------------------------------------------------
export interface SourceEnvelope<T> {
  as_of_ms: number | null;
  interval_s: number;
  present: boolean;
  seed: boolean;
  data: T | null;
}

export interface TapePayload {
  generated_ms: number;
  live_legal: false;
  size: 0;
  flow: SourceEnvelope<FlowOut>;
  gex: SourceEnvelope<GexOut>;
  doublewide: SourceEnvelope<LevelSourceOut>;
  aaron: SourceEnvelope<LevelSourceOut>;
  gates: { found: boolean; lockout: boolean | null; gates: { name: string; status: "pass" | "fail" | "warn" | "unknown" }[] };
}

const empty = <T,>(interval_s: number): SourceEnvelope<T> => ({ as_of_ms: null, interval_s, present: false, seed: false, data: null });

export function serializeFlow(raw: unknown): SourceEnvelope<FlowOut> {
  const data = flowShape(raw);
  if (!data) return empty(5);
  const asOf = data.as_of_epoch != null ? data.as_of_epoch * 1000 : null;
  return { as_of_ms: asOf, interval_s: data.interval_s ?? 5, present: true, seed: false, data };
}

export function serializeGex(raw: unknown): SourceEnvelope<GexOut> {
  const data = gexShape(raw);
  if (!data) return empty(900);
  // as_of is the SOURCE time (asof_ct), not the time our puller wrote the file.
  return { as_of_ms: ctWallToEpochMs(data.asof_ct), interval_s: 900, present: true, seed: false, data };
}

export function serializeLevelSource(raw: unknown, defaultIntervalS = 3600): SourceEnvelope<LevelSourceOut> {
  const data = levelSourceShape(raw);
  if (!data) return empty(defaultIntervalS);
  return {
    as_of_ms: ctWallToEpochMs(data.as_of_ct), interval_s: data.interval_s ?? defaultIntervalS,
    present: true, seed: data.seed === true, data,
  };
}

export function serializeGates(raw: unknown): TapePayload["gates"] {
  const none = { found: false, lockout: null, gates: [] };
  if (!isObj(raw)) return none;
  const gates = Array.isArray(raw.gates) ? raw.gates : [];
  const out: TapePayload["gates"]["gates"] = [];
  for (const g of gates.slice(0, 20)) {
    if (!isObj(g)) continue;
    const name = str(80)(g.name);
    // Footer shows gate names + state only: drop anything quoting R-multiples or dollars.
    if (!name || /\b\d+(\.\d+)?\s*R\b/.test(name)) continue;
    const status = oneOf("pass", "fail", "warn", "unknown")(g.status) ?? "unknown";
    out.push({ name, status });
  }
  return { found: raw.found === true, lockout: typeof raw.fileLockout === "boolean" ? raw.fileLockout : null, gates: out };
}

const PRIVATE_KEY = /pnl|p_l|position|account|equity|balance|cash|margin|buying|realized|netliq|net_liq|holding|order_id|fill/i;

/** Structural second line of defence: returns the offending key paths (empty = clean). */
export function findPrivateKeys(value: unknown, path = ""): string[] {
  const hits: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((v, i) => hits.push(...findPrivateKeys(v, `${path}[${i}]`)));
  } else if (isObj(value)) {
    for (const [k, v] of Object.entries(value)) {
      if (PRIVATE_KEY.test(k)) hits.push(`${path}.${k}`);
      hits.push(...findPrivateKeys(v, `${path}.${k}`));
    }
  } else if (typeof value === "string" && PRIVATE_TEXT.test(value)) {
    hits.push(`${path} (string)`);
  }
  return hits;
}

export interface TapeRawInputs {
  flow: unknown; gex: unknown; doublewide: unknown; aaron: unknown; gates: unknown;
}

export function buildTapePayload(raw: TapeRawInputs, nowMs: number): TapePayload {
  return {
    generated_ms: nowMs,
    live_legal: false,
    size: 0,
    flow: serializeFlow(raw.flow),
    gex: serializeGex(raw.gex),
    doublewide: serializeLevelSource(raw.doublewide),
    aaron: serializeLevelSource(raw.aaron),
    gates: serializeGates(raw.gates),
  };
}
