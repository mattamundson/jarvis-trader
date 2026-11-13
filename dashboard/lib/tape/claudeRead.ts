// Allow-list parser for ~/tape/state/claude-read-latest.json.
// Read-only. Unknown keys are dropped. Strings that carry dollars, P&L, or
// account language are dropped. Nothing here places an order or reads a broker.
import { currentGlobexTradingDate } from "@/lib/marketSession";

export const CLAUDE_READ_FILE = "claude-read-latest.json";
export const SIGNAL_NOT_A_FILL = "signal, not a fill";
/** Stale when written_at is strictly older than this during RTH. */
export const CLAUDE_READ_STALE_MS = 60 * 60 * 1000;
/** RTH window is inclusive: 08:30 through 15:00 America/Chicago, Monday–Friday. */
export const RTH_START_MIN = 8 * 60 + 30;
export const RTH_END_MIN = 15 * 60;

const PRIVATE_TEXT = /[$]|\bp\s*&\s*l\b|\bpnl\b|\bunrealized\b|\brealized\b|\bbuying power\b|\bnet liq/i;
const PRIVATE_KEY = /^(r|pnl|p&l|p_l|pl|fill|fills|position|positions|account|equity|balance|cash|margin|unrealized|realized|netliq|net_liq|buying_power|order_id|orderid)$/i;

type Rec = Record<string, unknown>;
const isObj = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const safeStr = (v: unknown, max: number): string | null =>
  typeof v === "string" && v.length > 0 && !PRIVATE_TEXT.test(v) ? v.slice(0, max) : null;

export type ClaudeKind = "plan" | "read" | "close";
export type ClaudeDirection = "above" | "below";
export type ClaudeTriggerStatus = "armed" | "signal" | "invalidated";
export type GammaRegime = "long" | "short" | "neutral";

export interface ClaudeReadPriorSession {
  date: string;
  close: number | null;
  low: number | null;
  close_note: string | null;
}

export interface ClaudeReadGamma {
  regime: GammaRegime | null;
  flip: number | null;
  pin: number | null;
  as_of: string | null;
}

export interface ClaudeReadContext {
  prior_sessions: ClaudeReadPriorSession[];
  vix_regime: string | null;
  event_implied_move: string | null;
  gamma: ClaudeReadGamma | null;
  stale: string[];
}

export interface ClaudeReadLevel {
  price: number;
  label: string | null;
}

export interface ClaudeReadTrigger {
  name: string;
  level: number;
  direction: ClaudeDirection;
  closes_needed: number;
  closes_seen: number;
  status: ClaudeTriggerStatus;
}

export interface ClaudeRead {
  version: 1;
  written_at: string;
  source: string | null;
  kind: ClaudeKind;
  context: ClaudeReadContext;
  bias: string | null;
  plan: string | null;
  levels: ClaudeReadLevel[];
  triggers: ClaudeReadTrigger[];
  note: string | null;
  live_legal: string | null;
}

export interface ClaudeReadFreshness {
  stale: boolean;
  duringRth: boolean;
  ageMs: number | null;
  ageMinutes: number | null;
  writtenAtCt: string | null;
  writtenTradingDay: string | null;
  currentTradingDay: string | null;
  reason: string;
}

export interface GammaFreshness {
  present: boolean;
  asOf: string | null;
  asOfCt: string | null;
  ageMs: number | null;
  ageMinutes: number | null;
  stale: boolean;
  reason: string;
}

export type ParseClaudeRead = { ok: true; read: ClaudeRead } | { ok: false; error: string };

export interface ClaudeReadPayload {
  ok: boolean;
  missing: boolean;
  malformed: boolean;
  error: string | null;
  file: typeof CLAUDE_READ_FILE;
  read: ClaudeRead | null;
  freshness: ClaudeReadFreshness | null;
  gamma: GammaFreshness | null;
}

const WEEKDAY: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

function chicagoClock(epochMs: number): { weekday: number; minutes: number } | null {
  if (!Number.isFinite(epochMs)) return null;
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  let weekday = -1;
  let hour = NaN;
  let minute = NaN;
  for (const part of fmt.formatToParts(new Date(epochMs))) {
    if (part.type === "weekday") weekday = WEEKDAY[part.value] ?? -1;
    else if (part.type === "hour") hour = Number(part.value === "24" ? "0" : part.value);
    else if (part.type === "minute") minute = Number(part.value);
  }
  if (weekday < 0 || !Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  return { weekday, minutes: hour * 60 + minute };
}

/** 08:30–15:00 America/Chicago, Monday through Friday, both ends inclusive. */
export function isRth(epochMs: number): boolean {
  const clock = chicagoClock(epochMs);
  if (!clock) return false;
  return clock.weekday >= 1 && clock.weekday <= 5 && clock.minutes >= RTH_START_MIN && clock.minutes <= RTH_END_MIN;
}

export function formatChicago(epochMs: number): string | null {
  if (!Number.isFinite(epochMs)) return null;
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const pick = (type: Intl.DateTimeFormatPartTypes) => fmt.formatToParts(new Date(epochMs)).find((p) => p.type === type)?.value ?? "";
  const hour = pick("hour") === "24" ? "00" : pick("hour");
  const y = pick("year");
  const m = pick("month");
  const d = pick("day");
  const min = pick("minute");
  if (!y || !m || !d || !hour || !min) return null;
  return `${y}-${m}-${d} ${hour}:${min} CT`;
}

/**
 * Stale during RTH (08:30–15:00 CT weekdays) when written_at is more than 60 minutes
 * old, or in the future. Outside that window, stale when written_at's Globex trading
 * day (CT date, rolled forward at 17:00 CT) is not the current Globex trading day.
 */
export function claudeReadFreshness(writtenAtIso: string, nowMs: number): ClaudeReadFreshness {
  const writtenMs = Date.parse(writtenAtIso);
  const currentTradingDay = currentGlobexTradingDate(nowMs);
  if (!Number.isFinite(writtenMs)) {
    return {
      stale: true, duringRth: isRth(nowMs), ageMs: null, ageMinutes: null, writtenAtCt: null,
      writtenTradingDay: null, currentTradingDay, reason: "written_at is not a valid time",
    };
  }
  const ageMs = nowMs - writtenMs;
  const ageMinutes = Math.round(ageMs / 60000);
  const duringRth = isRth(nowMs);
  const writtenTradingDay = currentGlobexTradingDate(writtenMs);
  const writtenAtCt = formatChicago(writtenMs);
  if (duringRth) {
    const future = ageMs < -60_000;
    const stale = future || ageMs > CLAUDE_READ_STALE_MS;
    const reason = future
      ? "written_at is in the future"
      : stale
        ? `written ${ageMinutes} min ago during RTH (limit 60 min)`
        : `written ${ageMinutes} min ago during RTH`;
    return { stale, duringRth, ageMs, ageMinutes, writtenAtCt, writtenTradingDay, currentTradingDay, reason };
  }
  const stale = !writtenTradingDay || !currentTradingDay || writtenTradingDay !== currentTradingDay;
  const reason = stale
    ? `written trading day ${writtenTradingDay ?? "unknown"}, current trading day ${currentTradingDay ?? "unknown"}`
    : `written on trading day ${writtenTradingDay} (outside RTH)`;
  return { stale, duringRth, ageMs, ageMinutes, writtenAtCt, writtenTradingDay, currentTradingDay, reason };
}

/** Gamma as-of is flagged when it is missing, unparseable, in the future, or older than 60 minutes. */
export function gammaFreshness(asOfIso: string | null, nowMs: number): GammaFreshness {
  if (!asOfIso) {
    return { present: false, asOf: null, asOfCt: null, ageMs: null, ageMinutes: null, stale: true, reason: "gamma as-of missing" };
  }
  const ms = Date.parse(asOfIso);
  if (!Number.isFinite(ms)) {
    return { present: true, asOf: null, asOfCt: null, ageMs: null, ageMinutes: null, stale: true, reason: "gamma as-of is not a valid time" };
  }
  const ageMs = nowMs - ms;
  const ageMinutes = Math.round(ageMs / 60000);
  const future = ageMs < -60_000;
  const stale = future || ageMs > CLAUDE_READ_STALE_MS;
  return {
    present: true,
    asOf: asOfIso,
    asOfCt: formatChicago(ms),
    ageMs,
    ageMinutes,
    stale,
    reason: future ? "gamma as-of is in the future" : stale ? `gamma as-of ${ageMinutes} min ago (limit 60 min)` : `gamma as-of ${ageMinutes} min ago`,
  };
}

function oneOf<T extends string>(v: unknown, opts: readonly T[]): T | null {
  return typeof v === "string" && (opts as readonly string[]).includes(v) ? (v as T) : null;
}

function priorSession(v: unknown): ClaudeReadPriorSession | null {
  if (!isObj(v)) return null;
  const date = safeStr(v.date, 10);
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  return { date, close: num(v.close), low: num(v.low), close_note: safeStr(v.close_note, 240) };
}

function gammaOf(v: unknown): ClaudeReadGamma | null {
  if (!isObj(v)) return null;
  const asOf = safeStr(v.as_of, 40);
  return { regime: oneOf(v.regime, ["long", "short", "neutral"] as const), flip: num(v.flip), pin: num(v.pin), as_of: asOf };
}

function contextOf(v: unknown): ClaudeReadContext | null {
  if (!isObj(v)) return null;
  const prior = Array.isArray(v.prior_sessions) ? v.prior_sessions.slice(0, 8).map(priorSession).filter((x): x is ClaudeReadPriorSession => x !== null) : [];
  const stale = Array.isArray(v.stale)
    ? v.stale.slice(0, 12).map((s) => safeStr(s, 160)).filter((s): s is string => s !== null)
    : [];
  return {
    prior_sessions: prior,
    vix_regime: safeStr(v.vix_regime, 160),
    event_implied_move: safeStr(v.event_implied_move, 240),
    gamma: v.gamma === undefined ? null : gammaOf(v.gamma),
    stale,
  };
}

function levelOf(v: unknown): ClaudeReadLevel | null {
  if (!isObj(v)) return null;
  const price = num(v.price);
  if (price === null) return null;
  return { price, label: safeStr(v.label, 120) };
}

function triggerOf(v: unknown): ClaudeReadTrigger | null {
  if (!isObj(v)) return null;
  const name = safeStr(v.name, 80);
  const level = num(v.level);
  const direction = oneOf(v.direction, ["above", "below"] as const);
  const closesNeeded = num(v.closes_needed);
  const closesSeen = num(v.closes_seen);
  const status = oneOf(v.status, ["armed", "signal", "invalidated"] as const);
  if (!name || level === null || !direction || closesNeeded === null || closesSeen === null || !status) return null;
  return { name, level, direction, closes_needed: closesNeeded, closes_seen: closesSeen, status };
}

/** Keep only the schema fields. Unknown keys, private keys, and dollar/P&L strings are dropped. */
export function parseClaudeRead(raw: unknown): ParseClaudeRead {
  if (!isObj(raw)) return { ok: false, error: "claude-read-latest.json is malformed" };
  if (raw.version !== 1) return { ok: false, error: "claude-read-latest.json is malformed: version must be 1" };
  if (typeof raw.written_at !== "string" || !Number.isFinite(Date.parse(raw.written_at))) {
    return { ok: false, error: "claude-read-latest.json is malformed: written_at must be an ISO time" };
  }
  const kind = oneOf(raw.kind, ["plan", "read", "close"] as const);
  if (!kind) return { ok: false, error: "claude-read-latest.json is malformed: kind must be plan, read, or close" };
  if (raw.context !== undefined && !isObj(raw.context)) return { ok: false, error: "claude-read-latest.json is malformed: context must be an object" };
  if (raw.levels !== undefined && !Array.isArray(raw.levels)) return { ok: false, error: "claude-read-latest.json is malformed: levels must be a list" };
  if (raw.triggers !== undefined && !Array.isArray(raw.triggers)) return { ok: false, error: "claude-read-latest.json is malformed: triggers must be a list" };
  const context = raw.context === undefined
    ? { prior_sessions: [], vix_regime: null, event_implied_move: null, gamma: null, stale: [] }
    : contextOf(raw.context);
  if (!context) return { ok: false, error: "claude-read-latest.json is malformed: context must be an object" };
  return {
    ok: true,
    read: {
      version: 1,
      written_at: raw.written_at,
      source: safeStr(raw.source, 40),
      kind,
      context,
      bias: safeStr(raw.bias, 400),
      plan: safeStr(raw.plan, 4000),
      levels: (Array.isArray(raw.levels) ? raw.levels : []).slice(0, 24).map(levelOf).filter((x): x is ClaudeReadLevel => x !== null),
      triggers: (Array.isArray(raw.triggers) ? raw.triggers : []).slice(0, 16).map(triggerOf).filter((x): x is ClaudeReadTrigger => x !== null),
      note: safeStr(raw.note, 2000),
      live_legal: safeStr(raw.live_legal, 80),
    },
  };
}

/** Second line of defence. Empty means the allow-listed value has no private key or dollar/P&L string. */
export function findPrivateKeys(value: unknown, path = ""): string[] {
  const hits: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((item, i) => hits.push(...findPrivateKeys(item, `${path}[${i}]`)));
  } else if (isObj(value)) {
    for (const [key, child] of Object.entries(value)) {
      if (PRIVATE_KEY.test(key)) hits.push(`${path}.${key}`);
      hits.push(...findPrivateKeys(child, `${path}.${key}`));
    }
  } else if (typeof value === "string" && PRIVATE_TEXT.test(value)) {
    hits.push(`${path} (string)`);
  }
  return hits;
}
