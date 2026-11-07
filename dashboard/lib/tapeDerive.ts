/**
 * Pure derivations for the /tape screen. No I/O, no React. Everything here is a readout of
 * the recorder snapshot (flow-latest.json); nothing trades or places orders.
 */

export const TAPE_STALE_AFTER_S = 60;
export const BIG_DELTA = 150;
export const VOL_SPIKE_MULT = 2;
export const VOL_AVG_BARS = 20;
export const DIVERGENCE_MINUTES = 10;
/** Minimum moves before a divergence is called, so noise is not flagged. */
export const DIVERGENCE_MIN_PRICE_PTS = 1;
export const DIVERGENCE_MIN_CVD = 50;
/** How many of the latest 1m bars the alert line looks back over for an absorption bar. */
export const ABSORB_LOOKBACK_BARS = 5;

export interface Bar1m {
  t: number; // epoch seconds, bar open
  o: number;
  h: number;
  l: number;
  c: number;
  /** null = missing/unknown in the source. NEVER fabricated to 0; analytics that need it are withheld. */
  vol: number | null;
  /** null = missing/unknown in the source. A genuine 0 stays 0. */
  delta: number | null;
  /** null = missing/unknown in the source. A genuine 0 stays 0. */
  cvd: number | null;
}

export interface TapeLevel {
  name: string;
  px: number;
  kind: string | null;
  dir: string | null;
  bias: string | null;
  status: string | null;
  note?: string | null;
}

export interface NqWindow {
  nq_pct: number | null;
  es_pct: number | null;
  rs: number | null;
}

export interface TapeSnapshot {
  asOfEpoch: number | null; // seconds
  asOfCt: string | null;
  price: { last: number; hi: number | null; lo: number | null; vwap: number | null };
  cvd: number | null;
  nq: {
    last: number | null;
    lead: string | null;
    windows: Record<string, NqWindow>;
  };
  levels: TapeLevel[];
  bars: Bar1m[];
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

/** Validate and normalise a raw flow-latest object. Returns null when it is unusable. Never throws. */
export function normalizeSnapshot(raw: unknown): TapeSnapshot | null {
  try {
    if (!raw || typeof raw !== "object") return null;
    const r = raw as Record<string, any>;
    const last = num(r.price?.last);
    if (last === null) return null;

    const bars: Bar1m[] = [];
    if (Array.isArray(r.series_1m)) {
      for (const b of r.series_1m) {
        const t = num(b?.t), o = num(b?.o), h = num(b?.h), l = num(b?.l), c = num(b?.c);
        if (t === null || o === null || h === null || l === null || c === null) continue;
        // Unknown vol/delta/cvd stay unknown (null) — never coerced to 0. Valid price
        // bars are kept even when their flow values are missing.
        bars.push({ t, o, h, l, c, vol: num(b.vol), delta: num(b.delta), cvd: num(b.cvd) });
      }
      bars.sort((a, b) => a.t - b.t);
    }

    const levels: TapeLevel[] = [];
    if (Array.isArray(r.levels)) {
      for (const lv of r.levels) {
        const px = num(lv?.px);
        if (px === null) continue;
        levels.push({
          name: str(lv.name) ?? "level",
          px,
          kind: str(lv.kind),
          dir: str(lv.dir),
          bias: str(lv.bias),
          status: str(lv.status),
          note: str(lv.note),
        });
      }
    }

    const windows: Record<string, NqWindow> = {};
    const rawWin = r.nq?.rel?.windows;
    if (rawWin && typeof rawWin === "object") {
      for (const k of Object.keys(rawWin)) {
        windows[k] = { nq_pct: num(rawWin[k]?.nq_pct), es_pct: num(rawWin[k]?.es_pct), rs: num(rawWin[k]?.rs) };
      }
    }

    let asOfEpoch = num(r.as_of_epoch);
    const asOfCt = str(r.as_of_ct);
    if (asOfEpoch === null && asOfCt) {
      const ms = Date.parse(asOfCt);
      if (Number.isFinite(ms)) asOfEpoch = Math.floor(ms / 1000);
    }

    return {
      asOfEpoch,
      asOfCt,
      price: { last, hi: num(r.price?.hi), lo: num(r.price?.lo), vwap: num(r.price?.vwap) },
      cvd: num(r.cvd?.value) ?? (bars.length ? bars[bars.length - 1].cvd : null),
      nq: { last: num(r.nq?.rel?.last), lead: str(r.nq?.rel?.lead), windows },
      levels,
      bars,
    };
  } catch {
    return null;
  }
}

/** Age in whole seconds of the snapshot at `nowMs`; null when as-of is unknown. */
export function ageSeconds(asOfEpoch: number | null, nowMs: number): number | null {
  if (asOfEpoch === null) return null;
  return Math.max(0, Math.round(nowMs / 1000 - asOfEpoch));
}

/** Unknown age counts as stale. */
export function isTapeStale(age: number | null, thresholdS: number = TAPE_STALE_AFTER_S): boolean {
  return age === null || age > thresholdS;
}

const CT_TIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** HH:MM in America/Chicago for an epoch in seconds. */
export function fmtCt(epochS: number): string {
  const parts = CT_TIME.formatToParts(new Date(epochS * 1000));
  const hh = parts.find((p) => p.type === "hour")?.value ?? "00";
  const mm = parts.find((p) => p.type === "minute")?.value ?? "00";
  return `${hh === "24" ? "00" : hh}:${mm}`;
}

function chicagoParts(epochMs: number) {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  const o: Record<string, number> = {};
  for (const p of f.formatToParts(new Date(epochMs))) if (p.type !== "literal") o[p.type] = Number(p.value);
  if (o.hour === 24) o.hour = 0;
  return o;
}

/** Epoch seconds of the most recent HH:MM Chicago wall-clock time at or before `epochS`. */
export function lastChicagoWallTime(epochS: number, hh: number, mm: number): number {
  const at = (dayShift: number): number => {
    const p = chicagoParts(epochS * 1000);
    const wallUtc = Date.UTC(p.year, p.month - 1, p.day + dayShift, hh, mm, 0);
    let guess = wallUtc + 6 * 3600_000;
    for (let i = 0; i < 3; i++) {
      const g = chicagoParts(guess);
      const gotWall = Date.UTC(g.year, g.month - 1, g.day, g.hour, g.minute, 0);
      guess += wallUtc - gotWall;
    }
    return Math.floor(guess / 1000);
  };
  const today = at(0);
  return today <= epochS ? today : at(-1);
}

export interface BarRow {
  t: number;
  time: string;
  close: number;
  range: number;
  vol: number;
  delta: number;
  cvd: number;
  bigDelta: boolean;
  volSpike: boolean;
  /** Average volume of the up-to-20 bars before this one (null if none). */
  avgVol: number | null;
  /** Bar move (close minus open). */
  move: number;
  /** "up" = positive delta but price closed lower (buying absorbed). "down" = negative delta but price closed higher (selling absorbed). */
  absorb: "up" | "down" | null;
}

/** |delta| >= BIG_DELTA while the bar closed against the delta sign. Unknown delta → withheld (null). */
export function absorptionOf(b: Pick<Bar1m, "o" | "c" | "delta">): "up" | "down" | null {
  if (b.delta === null || Math.abs(b.delta) < BIG_DELTA) return null;
  const move = b.c - b.o;
  if (b.delta > 0 && move < 0) return "up";
  if (b.delta < 0 && move > 0) return "down";
  return null;
}

export function recentBars(bars: Bar1m[], n = 15): BarRow[] {
  const start = Math.max(0, bars.length - n);
  const rows: BarRow[] = [];
  for (let i = start; i < bars.length; i++) {
    const b = bars[i];
    const prior = bars.slice(Math.max(0, i - VOL_AVG_BARS), i);
    // Average volume over KNOWN prior bars only; unknown values neither fabricate nor dilute it.
    const knownVols = prior.filter((x) => x.vol !== null).map((x) => x.vol as number);
    const avgVol = knownVols.length ? knownVols.reduce((s, x) => s + x, 0) / knownVols.length : null;
    rows.push({
      t: b.t,
      time: fmtCt(b.t),
      close: b.c,
      range: Math.round((b.h - b.l) * 100) / 100,
      // Unknown flow values render as NaN → "--" via fmtSigned / neutral colour; never a fake 0.
      vol: b.vol ?? NaN,
      delta: b.delta ?? NaN,
      cvd: b.cvd ?? NaN,
      bigDelta: b.delta !== null && Math.abs(b.delta) >= BIG_DELTA,
      volSpike: b.vol !== null && avgVol !== null && avgVol > 0 && b.vol >= VOL_SPIKE_MULT * avgVol,
      avgVol,
      move: Math.round((b.c - b.o) * 100) / 100,
      absorb: absorptionOf(b),
    });
  }
  return rows;
}

export interface Block15 {
  start: number;
  label: string;
  vol: number;
  delta: number;
  open: number;
  close: number;
  bars: number;
  partial: boolean;
}

/** Group 1-minute bars into 15-minute blocks (aligned to :00/:15/:30/:45). Oldest first. */
export function blocks15(bars: Bar1m[]): Block15[] {
  const map = new Map<number, Bar1m[]>();
  for (const b of bars) {
    const k = Math.floor(b.t / 900) * 900;
    const arr = map.get(k);
    if (arr) arr.push(b);
    else map.set(k, [b]);
  }
  return [...map.keys()]
    .sort((a, b) => a - b)
    .map((k) => {
      const arr = map.get(k)!;
      return {
        start: k,
        label: fmtCt(k),
        // A block containing an unknown value reports unknown (NaN → "--" on render), never 0.
        vol: arr.reduce((s, x) => s + (x.vol ?? NaN), 0),
        delta: arr.reduce((s, x) => s + (x.delta ?? NaN), 0),
        open: arr[0].o,
        close: arr[arr.length - 1].c,
        bars: arr.length,
        partial: arr.length < 15,
      };
    });
}

export interface PriceRow {
  price: number;
  vol: number;
  delta: number;
  bars: number;
}

/** Volume and delta at price, by each bar's close rounded to a whole point, bars at/after sinceEpoch. Highest price first. */
export function profileAtPrice(bars: Bar1m[], sinceEpoch: number): PriceRow[] {
  const map = new Map<number, PriceRow>();
  for (const b of bars) {
    if (b.t < sinceEpoch) continue;
    const p = Math.round(b.c);
    const row = map.get(p) ?? { price: p, vol: 0, delta: 0, bars: 0 };
    // Unknown vol/delta poison the whole price row to NaN (withheld), never a silent 0.
    row.vol += b.vol ?? NaN;
    row.delta += b.delta ?? NaN;
    row.bars += 1;
    map.set(p, row);
  }
  return [...map.values()].sort((a, b) => b.price - a.price);
}

export interface LevelRow extends TapeLevel {
  /** px minus last: positive means the level is above price. */
  dist: number;
  side: "above" | "below" | "at";
}

export function levelRows(levels: TapeLevel[], last: number): LevelRow[] {
  return levels
    .map((l) => {
      const dist = Math.round((l.px - last) * 100) / 100;
      return { ...l, dist, side: dist > 0 ? ("above" as const) : dist < 0 ? ("below" as const) : ("at" as const) };
    })
    .sort((a, b) => b.px - a.px);
}

export interface SupportResistance {
  support: LevelRow | null;
  resistance: LevelRow | null;
  state: string;
}

const NEAR_PTS = 2;

/** Nearest level at/below price (support) and above price (resistance), plus a one-line state. */
export function nearestSupportResistance(rows: LevelRow[]): SupportResistance {
  let support: LevelRow | null = null;
  let resistance: LevelRow | null = null;
  for (const r of rows) {
    if (r.dist <= 0) {
      if (!support || r.dist > support.dist) support = r;
    } else if (!resistance || r.dist < resistance.dist) resistance = r;
  }
  const fmt = (r: LevelRow) => `${r.name} ${r.px} (${r.dist > 0 ? "+" : ""}${r.dist})`;
  let state: string;
  if (!support && !resistance) state = "No levels loaded.";
  else if (!support) state = `Below every level. Resistance ${fmt(resistance!)}.`;
  else if (!resistance) state = `Above every level. Support ${fmt(support)}.`;
  else {
    const nearS = Math.abs(support.dist) <= NEAR_PTS;
    const nearR = resistance.dist <= NEAR_PTS;
    if (nearS && nearR) state = `Pinned between support ${fmt(support)} and resistance ${fmt(resistance)}.`;
    else if (nearS) state = `Sitting on support ${fmt(support)}. Resistance ${fmt(resistance)}.`;
    else if (nearR) state = `Pressing resistance ${fmt(resistance)}. Support ${fmt(support)}.`;
    else state = `Between support ${fmt(support)} and resistance ${fmt(resistance)}.`;
  }
  return { support, resistance, state };
}

export interface TapeAlert {
  kind: "divergence" | "nq-rs" | "absorption";
  text: string;
}

const sgn = (n: number) => (n > 0 ? "+" : "");

/** Plain alert lines. Empty array when nothing is diverging. */
export function tapeAlerts(snap: TapeSnapshot, minutes: number = DIVERGENCE_MINUTES): TapeAlert[] {
  const out: TapeAlert[] = [];
  const bars = snap.bars;
  if (bars.length > minutes) {
    const now = bars[bars.length - 1];
    const then = bars[bars.length - 1 - minutes];
    const dp = Math.round((now.c - then.c) * 100) / 100;
    // Divergence is asserted only from KNOWN CVD values on both ends. A missing CVD must
    // never be coerced to 0 — that fabricated bearish divergences out of missing data.
    if (now.cvd !== null && then.cvd !== null) {
      const dc = now.cvd - then.cvd;
      if (dp >= DIVERGENCE_MIN_PRICE_PTS && dc <= -DIVERGENCE_MIN_CVD) {
        out.push({
          kind: "divergence",
          text: `Bearish divergence: ES up ${sgn(dp)}${dp} over ${minutes}m while CVD fell ${dc}. Lift on no buying.`,
        });
      } else if (dp <= -DIVERGENCE_MIN_PRICE_PTS && dc >= DIVERGENCE_MIN_CVD) {
        out.push({
          kind: "divergence",
          text: `Bullish divergence: ES down ${dp} over ${minutes}m while CVD rose ${sgn(dc)}${dc}. Selling is being absorbed.`,
        });
      }
    }
  }
  const w = snap.nq.windows["30m"];
  if (w && w.rs !== null && w.rs < 0 && w.es_pct !== null && w.es_pct > 0) {
    out.push({
      kind: "nq-rs",
      text: `NQ lagging: 30m relative strength ${w.rs} while ES is rising (${sgn(w.es_pct)}${w.es_pct}%).`,
    });
  }
  // Absorption: big delta, price went the other way, within the last few bars.
  for (let i = bars.length - 1; i >= Math.max(0, bars.length - ABSORB_LOOKBACK_BARS); i--) {
    const b = bars[i];
    const a = absorptionOf(b);
    if (!a || b.delta === null) continue; // a !== null already implies a known delta; the guard narrows it for TS
    const delta = b.delta;
    const mv = Math.round((b.c - b.o) * 100) / 100;
    out.push({
      kind: "absorption",
      text:
        a === "up"
          ? `Absorption ${fmtCt(b.t)}: delta ${sgn(delta)}${delta} but ES closed lower (${mv}). Buying absorbed by sellers.`
          : `Absorption ${fmtCt(b.t)}: delta ${delta} but ES closed higher (${sgn(mv)}${mv}). Selling absorbed by buyers.`,
    });
    break;
  }
  return out;
}

export function fmtNum(n: number | null | undefined, digits = 2): string {
  return n === null || n === undefined || !Number.isFinite(n) ? "--" : n.toFixed(digits);
}
export function fmtSigned(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "--";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
}
export function fmtAgeShort(age: number | null): string {
  if (age === null) return "age unknown";
  if (age < 90) return `${age}s`;
  if (age < 5400) return `${Math.round(age / 60)}m`;
  if (age < 172800) return `${Math.round(age / 3600)}h`;
  return `${Math.round(age / 86400)}d`;
}
// ---- Gamma levels (ZeroGEX snapshot, ~15-20 min delayed) ----

export const GEX_STALE_AFTER_MIN = 30;

export interface GexInfo {
  asOfCt: string | null;
  asOfEpoch: number | null;
  ageMin: number | null;
  stale: boolean;
  flip: number | null;
  callWall: number | null;
  putWall: number | null;
  maxPain: number | null;
  source: string | null;
  levels: TapeLevel[];
}

/** "YYYY-MM-DD HH:MM" America/Chicago wall time to epoch seconds. Null when unparseable. */
export function chicagoWallToEpoch(s: string | null | undefined): number | null {
  const m = typeof s === "string" ? s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/) : null;
  if (!m) return null;
  const asUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date(asUtc));
  const g = (t: string) => +(parts.find((p) => p.type === t)?.value ?? 0);
  const shown = Date.UTC(g("year"), g("month") - 1, g("day"), g("hour") % 24, g("minute"));
  return Math.round((asUtc + (asUtc - shown)) / 1000);
}

/** Normalize the gex block from /api/flow/tape. Null when missing. Never throws. Values are passed through, never invented. */
export function normalizeGex(raw: unknown, nowMs: number): GexInfo | null {
  try {
    if (!raw || typeof raw !== "object") return null;
    const r = raw as Record<string, any>;
    const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
    const asOfCt = typeof r.asof_ct === "string" ? r.asof_ct : null;
    const asOfEpoch = chicagoWallToEpoch(asOfCt);
    const ageMin = asOfEpoch === null ? null : Math.max(0, Math.floor((nowMs / 1000 - asOfEpoch) / 60));
    const stale = ageMin === null || ageMin > GEX_STALE_AFTER_MIN || r.fetch_ok === false;
    const info: GexInfo = { asOfCt, asOfEpoch, ageMin, stale, flip: num(r.flip), callWall: num(r.call_wall), putWall: num(r.put_wall), maxPain: num(r.max_pain), source: typeof r.source === "string" ? r.source : null, levels: [] };
    const hhmm = asOfCt ? asOfCt.slice(11, 16) : "?";
    const status = `ZeroGEX ${hhmm} CT, ${ageMin === null ? "age ?" : `${ageMin}m`}${stale ? " STALE" : ""}`;
    const add = (name: string, px: number | null) => {
      if (px !== null) info.levels.push({ name, px, kind: "gex", dir: null, bias: null, status, note: null });
    };
    add("Gamma flip", info.flip);
    add("Call wall", info.callWall);
    add("Put wall", info.putWall);
    add("Max pain", info.maxPain);
    return info;
  } catch {
    return null;
  }
}