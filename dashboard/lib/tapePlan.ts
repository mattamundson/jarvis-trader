/**
 * Trigger plan, trigger evaluation, level merging and chart geometry for /tape.
 * Pure functions, no I/O. Readout only: nothing here places or suggests an order.
 */
import { absorptionOf, fmtCt, fmtNum, fmtSigned, type Bar1m, type TapeLevel, type TapeSnapshot } from "@/lib/tapeDerive";

export interface SidePlan {
  trigger: number;
  minDelta: number;
  targets: number[];
  stop: number | null;
}

export interface TapePlan {
  date: string | null;
  note: string | null;
  nqRef: number | null;
  lookbackMin: number;
  /** Minutes after a failure with no new break before FAILED reverts to ARMED. */
  failedExpiryMin: number;
  long: SidePlan | null;
  short: SidePlan | null;
  extraLevels: TapeLevel[];
}

export const DEFAULT_FAILED_EXPIRY_MIN = 15;

const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function side(raw: any): SidePlan | null {
  const trigger = n(raw?.trigger);
  if (trigger === null) return null;
  const minDelta = Math.abs(n(raw?.minDelta) ?? 150);
  const targets = Array.isArray(raw?.targets) ? (raw.targets.map(n).filter((x: number | null) => x !== null) as number[]) : [];
  return { trigger, minDelta, targets, stop: n(raw?.stop) };
}

/** Validate the plan JSON. Returns null when it is not an object. Never throws. */
export function normalizePlan(raw: unknown): TapePlan | null {
  try {
    if (!raw || typeof raw !== "object") return null;
    const r = raw as Record<string, any>;
    const extraLevels: TapeLevel[] = [];
    if (Array.isArray(r.extraLevels)) {
      for (const l of r.extraLevels) {
        const px = n(l?.px);
        if (px === null) continue;
        extraLevels.push({
          name: typeof l.name === "string" ? l.name : "plan level",
          px,
          kind: "plan",
          dir: null,
          bias: null,
          status: typeof l.status === "string" ? l.status : "plan",
          note: typeof l.note === "string" ? l.note : null,
        });
      }
    }
    return {
      date: typeof r.date === "string" ? r.date : null,
      note: typeof r.note === "string" ? r.note : null,
      nqRef: n(r.nqRef),
      lookbackMin: Math.max(10, n(r.lookbackMin) ?? 90),
      failedExpiryMin: Math.max(1, n(r.failedExpiryMin) ?? DEFAULT_FAILED_EXPIRY_MIN),
      long: side(r.long),
      short: side(r.short),
      extraLevels,
    };
  } catch {
    return null;
  }
}

/** Recorder levels plus plan levels. A plan level is dropped when the recorder already has the same name and price. */
export function mergeLevels(recorder: TapeLevel[], extra: TapeLevel[]): TapeLevel[] {
  const out = [...recorder];
  for (const e of extra) {
    const dup = out.some((l) => Math.abs(l.px - e.px) < 0.01 && l.name.toLowerCase() === e.name.toLowerCase());
    if (!dup) out.push(e);
  }
  return out;
}

export interface Bar5m {
  start: number;
  o: number;
  h: number;
  l: number;
  c: number;
  vol: number;
  delta: number;
}

/** Completed 5-minute bars (aligned to :00/:05...) from 1m bars. A bar is complete once asOf has reached its end. Oldest first. */
export function completed5m(bars: Bar1m[], asOfEpoch: number): Bar5m[] {
  const map = new Map<number, Bar1m[]>();
  for (const b of bars) {
    const k = Math.floor(b.t / 300) * 300;
    const arr = map.get(k);
    if (arr) arr.push(b);
    else map.set(k, [b]);
  }
  return [...map.keys()]
    .sort((a, b) => a - b)
    .filter((k) => k + 300 <= asOfEpoch)
    .map((k) => {
      const arr = map.get(k)!;
      return {
        start: k,
        o: arr[0].o,
        h: Math.max(...arr.map((x) => x.h)),
        l: Math.min(...arr.map((x) => x.l)),
        c: arr[arr.length - 1].c,
        // A bucket containing an unknown value is itself unknown (NaN): it can never
        // confirm or deny a trigger gate downstream. Genuine zeros stay zeros.
        vol: arr.reduce((s, x) => s + (x.vol ?? NaN), 0),
        delta: arr.reduce((s, x) => s + (x.delta ?? NaN), 0),
      };
    });
}

export type TriggerStatus = "ARMED" | "TRIGGERED" | "FAILED";

export interface TriggerCheck {
  label: string;
  ok: boolean;
  detail: string;
}

export interface TriggerEval {
  side: "long" | "short";
  status: TriggerStatus;
  plan: SidePlan;
  checks: TriggerCheck[];
  /** Epoch seconds of the most recent failure in the lookback window, if any (also set once it has expired). */
  failedAt: number | null;
  /** Small note shown once a failure has expired, e.g. "failed 07:30, re-armed". */
  reArmedNote: string | null;
  /** One line: why the status is what it is. */
  reason: string;
  /** The if/then sentence for this side, built from the plan. */
  ifThen: string;
}

export function ifThenText(sideName: "long" | "short", p: SidePlan, nqRef: number | null): string {
  const long = sideName === "long";
  const dir = long ? "above" : "below";
  const dsign = long ? "+" : "-";
  const nqTxt = nqRef === null ? "" : ` AND NQ ${dir} ${nqRef}`;
  const tg = p.targets.length ? `targets ${p.targets.join(" / ")}` : "no targets set";
  const stop = p.stop === null ? "no stop set" : `stop ${long ? "under" : "over"} ${p.stop}`;
  return `IF 5m closes ${dir} ${p.trigger} AND 1m delta ${long ? ">=" : "<="} ${dsign}${p.minDelta}${nqTxt} THEN ${tg}, ${stop}`;
}

/** Evaluate one side of the plan against the snapshot. ARMED, TRIGGERED or FAILED, with the check list. */
export function evaluateTrigger(sideName: "long" | "short", p: SidePlan, snap: TapeSnapshot, nqRef: number | null, lookbackMin: number, failedExpiryMin: number = DEFAULT_FAILED_EXPIRY_MIN): TriggerEval {
  const sg = sideName === "long" ? 1 : -1;
  const beyond = (px: number) => sg * (px - p.trigger) > 0;
  const hitStop = (b: { h: number; l: number }) => p.stop !== null && (sg === 1 ? b.l <= p.stop : b.h >= p.stop);
  const asOf = snap.asOfEpoch ?? (snap.bars.length ? snap.bars[snap.bars.length - 1].t + 60 : 0);
  const from = asOf - lookbackMin * 60;
  const five = completed5m(snap.bars, asOf).filter((b) => b.start >= from);
  const confirmedIn = (a: number, z: number) => snap.bars.some((b) => b.t >= a && b.t < z && b.delta !== null && sg * b.delta >= p.minDelta);

  let breakStart: number | null = null;
  let failedReason: string | null = null;
  let failedAt: number | null = null;
  for (const b of five) {
    if (breakStart !== null) {
      // Stop touched on any bar after the break bar closed.
      if (b.start >= breakStart + 300 && hitStop(b)) {
        failedReason = `stop ${p.stop} touched at ${fmtCt(b.start)} after the break`;
        failedAt = b.start;
        breakStart = null;
      }
    }
    if (beyond(b.c)) {
      if (breakStart === null) {
        breakStart = b.start;
        failedReason = null;
        failedAt = null;
      }
    } else if (breakStart !== null) {
      if (confirmedIn(breakStart, b.start + 300)) {
        failedReason = `5m close ${fmtNum(b.c)} back through ${p.trigger} at ${fmtCt(b.start)} after a confirmed break`;
        failedAt = b.start + 300;
      }
      breakStart = null;
    }
  }
  // Partial bars after the last completed 5m bar: stop check on 1m highs/lows.
  const lastDone = five.length ? five[five.length - 1].start + 300 : from;
  if (breakStart !== null) {
    const tail = snap.bars.filter((b) => b.t >= lastDone && b.t >= breakStart! + 300);
    const hit = tail.find(hitStop);
    if (hit || (p.stop !== null && (sg === 1 ? snap.price.last <= p.stop : snap.price.last >= p.stop))) {
      failedReason = `stop ${p.stop} touched after the break`;
      failedAt = hit ? hit.t : asOf;
      breakStart = null;
    }
  }

  const lastClose = five.length ? five[five.length - 1].c : null;
  const nqOk = snap.nq.last !== null && nqRef !== null && sg * (snap.nq.last - nqRef) > 0;
  const nqDetail =
    snap.nq.last === null || nqRef === null
      ? "NQ or reference missing"
      : `NQ ${fmtNum(snap.nq.last)} vs ${nqRef} (${fmtSigned(snap.nq.last - nqRef, 2)})`;
  const recentFrom = asOf - 300;
  const deltaFrom = breakStart ?? recentFrom;
  const deltaBars = snap.bars.filter((b) => b.t >= deltaFrom);
  // Unknown deltas cannot satisfy the gate (fail closed); a genuine 0 delta is known but insufficient.
  const knownDeltaBars = deltaBars.filter(b => b.delta !== null && Number.isFinite(b.delta));
  const bestDelta = knownDeltaBars.reduce<number | null>((m, b) => m === null || sg * b.delta! > sg * m ? b.delta : m, null);
  const deltaOk = bestDelta !== null && sg * bestDelta >= p.minDelta;
  const checks: TriggerCheck[] = [
    {
      label: `5m close ${sideName === "long" ? "above" : "below"} ${p.trigger}`,
      ok: breakStart !== null,
      detail: lastClose === null ? "no completed 5m bar" : `last 5m close ${fmtNum(lastClose)} (${fmtSigned(lastClose - p.trigger, 2)})`,
    },
    {
      label: `1m delta ${sg === 1 ? ">=" : "<="} ${sg === 1 ? "+" : "-"}${p.minDelta}`,
      ok: deltaOk,
      detail: bestDelta === null ? "delta unavailable" : `best ${fmtSigned(bestDelta)} ${breakStart !== null ? "since break" : "last 5m"}`,
    },
    { label: `NQ ${sg === 1 ? "above" : "below"} ${nqRef ?? "--"}`, ok: nqOk, detail: nqDetail },
  ];

  let status: TriggerStatus = "ARMED";
  let reason: string;
  let reArmedNote: string | null = null;
  if (breakStart === null && failedReason !== null && failedAt !== null && asOf - failedAt >= failedExpiryMin * 60) {
    // Failure is old enough and there has been no new break: back to ARMED, keep a small note.
    reArmedNote = `failed ${fmtCt(failedAt)}, re-armed`;
    reason = `waiting on: ${checks.filter((c) => !c.ok).map((c) => c.label).join("; ")}`;
  } else if (breakStart === null && failedReason !== null) {
    status = "FAILED";
    reason = failedReason;
  } else if (checks.every((c) => c.ok)) {
    status = "TRIGGERED";
    reason = `all three met, break bar ${fmtCt(breakStart ?? 0)}`;
  } else {
    const missing = checks.filter((c) => !c.ok).map((c) => c.label);
    reason = `waiting on: ${missing.join("; ")}`;
  }
  return { side: sideName, status, plan: p, checks, failedAt: failedReason !== null && breakStart === null ? failedAt : null, reArmedNote, reason, ifThen: ifThenText(sideName, p, nqRef) };
}

export interface TriggerPanel {
  bias: string;
  long: TriggerEval | null;
  short: TriggerEval | null;
}

// ---- Plan-of-record availability (truthfulness gate) ----

export interface PlanAvailability {
  usable: boolean;
  kind: "ok" | "missing_plan" | "missing_date" | "stale_date" | "wrong_session" | "conflict";
  reason: string;
}

const PLAN_DATE_RE = /dated (\d{4}-\d{2}-\d{2})/;

/**
 * Decide whether the dashboard plan file may back ACTIONABLE trigger evaluation.
 * A stale, wrong-session, or plan-source-conflicting file is reported unavailable —
 * the dashboard never auto-picks between the dashboard config plan and the recorder's
 * plan of record, and never falls back silently to either.
 */
export function planAvailability(
  plan: TapePlan | null,
  args: {
    todayCt: string | null;
    globexTradingDate: string | null;
    recorderSessionTradingDay: string | null;
    recorderLevelsSource: string | null;
  },
): PlanAvailability {
  if (!plan) {
    return { usable: false, kind: "missing_plan", reason: "plan missing or invalid" };
  }
  if (!plan.date) {
    return { usable: false, kind: "missing_date", reason: "plan file has no date field" };
  }
  // Evening Globex belongs to the NEXT trading date, not the calendar date.
  const expectedDate = args.globexTradingDate ?? args.todayCt;
  if (!expectedDate) {
    return { usable: false, kind: "missing_date", reason: "current trading-session date unavailable" };
  }
  if (plan.date !== expectedDate) {
    const wrongSession = plan.date === args.todayCt && expectedDate !== args.todayCt;
    return { usable: false, kind: wrongSession ? "wrong_session" : "stale_date",
      reason: `plan dated ${plan.date}, current trading session is ${expectedDate} — ${wrongSession ? "wrong session" : "stale plan"}` };
  }
  if (args.recorderSessionTradingDay && plan.date !== args.recorderSessionTradingDay) {
    return {
      usable: false,
      kind: "wrong_session",
      reason: `plan dated ${plan.date} but recorder session trading day is ${args.recorderSessionTradingDay} — wrong session`,
    };
  }
  const m = typeof args.recorderLevelsSource === "string" ? args.recorderLevelsSource.match(PLAN_DATE_RE) : null;
  if (m && m[1] !== plan.date) {
    return {
      usable: false,
      kind: "conflict",
      reason: `recorder serves plan dated ${m[1]} while dashboard plan is dated ${plan.date} — conflicting plan sources, not auto-resolved`,
    };
  }
  return { usable: true, kind: "ok", reason: "plan date matches today and the recorder's plan of record" };
}

/** Build the one-line bias and the two evaluated sides. */
export function triggerPanel(snap: TapeSnapshot, plan: TapePlan): TriggerPanel {
  const long = plan.long ? evaluateTrigger("long", plan.long, snap, plan.nqRef, plan.lookbackMin, plan.failedExpiryMin) : null;
  const short = plan.short ? evaluateTrigger("short", plan.short, snap, plan.nqRef, plan.lookbackMin, plan.failedExpiryMin) : null;
  const last = snap.price.last;

  let zone: string;
  if (plan.long && last > plan.long.trigger) zone = `above long trigger ${plan.long.trigger} (${fmtSigned(last - plan.long.trigger, 2)})`;
  else if (plan.short && last < plan.short.trigger) zone = `below short trigger ${plan.short.trigger} (${fmtSigned(last - plan.short.trigger, 2)})`;
  else if (plan.long && plan.short) zone = `inside ${plan.short.trigger}-${plan.long.trigger} box`;
  else zone = "no trigger zone set";

  const votes: number[] = [];
  const notes: string[] = [];
  if (snap.price.vwap !== null) {
    const d = last - snap.price.vwap;
    votes.push(Math.sign(d));
    notes.push(`${d >= 0 ? "above" : "below"} VWAP ${fmtSigned(d, 2)}`);
  }
  if (snap.bars.length > 10) {
    const nowCvd = snap.bars[snap.bars.length - 1].cvd;
    const thenCvd = snap.bars[snap.bars.length - 11].cvd;
    // The CVD vote is asserted only from known values on both ends; a missing CVD is
    // withheld (no vote), never read as zero.
    if (nowCvd !== null && thenCvd !== null) {
      const d = nowCvd - thenCvd;
      votes.push(Math.sign(d));
      notes.push(`CVD 10m ${fmtSigned(d)}`);
    }
  }
  if (snap.nq.last !== null && plan.nqRef !== null) {
    const d = snap.nq.last - plan.nqRef;
    votes.push(Math.sign(d));
    notes.push(`NQ ${d >= 0 ? "above" : "below"} ref`);
  }
  const sum = votes.reduce((a, b) => a + b, 0);

  let label: string;
  if (long?.status === "TRIGGERED" && short?.status !== "TRIGGERED") label = "LONG TRIGGERED";
  else if (short?.status === "TRIGGERED" && long?.status !== "TRIGGERED") label = "SHORT TRIGGERED";
  else if (long?.status === "TRIGGERED" && short?.status === "TRIGGERED") label = "CONFLICT (both triggered)";
  else if (sum >= 2) label = "LEAN LONG, no trigger yet";
  else if (sum <= -2) label = "LEAN SHORT, no trigger yet";
  else label = "NEUTRAL, no trigger";
  return { bias: `${label}: ${zone}; ${notes.join("; ")}`, long, short };
}

// ---- Mini chart geometry ----

export interface ChartLine {
  y: number;
  label: string;
  kind: "vwap" | "level" | "trigger" | "price";
}
export interface ChartModel {
  width: number;
  priceH: number;
  deltaH: number;
  height: number;
  candles: { x: number; w: number; yO: number; yC: number; yH: number; yL: number; up: boolean; absorb: boolean }[];
  deltaBars: { x: number; w: number; y: number; h: number; pos: boolean; big: boolean }[];
  deltaZeroY: number;
  lines: ChartLine[];
  min: number;
  max: number;
  count: number;
  timeLabels: { x: number; text: string }[];
  /** Right edge of the plot area; line labels start at labelX. */
  plotRight: number;
  labelX: number;
}

export interface ChartInput {
  snap: TapeSnapshot;
  levels: TapeLevel[];
  plan: TapePlan | null;
  minutes?: number;
  width?: number;
  priceH?: number;
  deltaH?: number;
  /** Right margin reserved for line labels. */
  rightPad?: number;
}

/** Geometry for the SVG mini chart of the last N 1m bars with delta bars underneath. */
export function chartModel(input: ChartInput): ChartModel | null {
  const { snap, levels, plan } = input;
  const minutes = input.minutes ?? 90;
  const width = input.width ?? 900;
  const priceH = input.priceH ?? 240;
  const deltaH = input.deltaH ?? 56;
  const rightPad = input.rightPad ?? 150;
  const bars = snap.bars.slice(-minutes);
  if (bars.length === 0) return null;

  const last = snap.price.last;
  let lo = Math.min(...bars.map((b) => b.l));
  let hi = Math.max(...bars.map((b) => b.h));
  const extra: number[] = [];
  if (snap.price.vwap !== null) extra.push(snap.price.vwap);
  if (plan?.long) extra.push(plan.long.trigger);
  if (plan?.short) extra.push(plan.short.trigger);
  let above: number | null = null;
  let below: number | null = null;
  for (const l of levels) {
    if (l.px > last && (above === null || l.px < above)) above = l.px;
    if (l.px <= last && (below === null || l.px > below)) below = l.px;
  }
  // Nearest resistance and support stretch the range only when they are close (within 8 pts), so a far level cannot flatten the candles.
  const NEAR = 8;
  if (above !== null && above - hi <= NEAR) extra.push(above);
  if (below !== null && lo - below <= NEAR) extra.push(below);
  for (const e of extra) {
    lo = Math.min(lo, e);
    hi = Math.max(hi, e);
  }
  const pad = Math.max(0.5, (hi - lo) * 0.04);
  lo -= pad;
  hi += pad;
  const plotRight = width - rightPad;
  const plotW = plotRight - 4;
  const step = plotW / Math.max(bars.length, 1);
  const bw = Math.max(1, step * 0.65);
  const y = (px: number) => 4 + ((hi - px) / (hi - lo)) * (priceH - 8);
  const r2 = (v: number) => Math.round(v * 100) / 100;

  const candles = bars.map((b, i) => ({
    x: r2(4 + i * step + step / 2),
    w: r2(bw),
    yO: r2(y(b.o)),
    yC: r2(y(b.c)),
    yH: r2(y(b.h)),
    yL: r2(y(b.l)),
    up: b.c >= b.o,
    absorb: absorptionOf(b) !== null,
  }));

  // Unknown-delta bars are withheld from the histogram (a gap), never drawn as a zero-height bar.
  const knownDeltas = bars.map((b) => b.delta).filter((d): d is number => d !== null && Number.isFinite(d));
  const maxAbs = Math.max(1, ...knownDeltas.map((d) => Math.abs(d)));
  const zeroY = priceH + 6 + (deltaH - 6) / 2;
  const half = (deltaH - 6) / 2;
  const deltaBars = bars.flatMap((b, i) => {
    if (b.delta === null) return [];
    const h = (Math.abs(b.delta) / maxAbs) * half;
    return [{
      x: r2(4 + i * step + step / 2),
      w: r2(bw),
      y: r2(b.delta >= 0 ? zeroY - h : zeroY),
      h: r2(Math.max(0.5, h)),
      pos: b.delta >= 0,
      big: Math.abs(b.delta) >= 150,
    }];
  });

  const lines: ChartLine[] = [];
  const inRange = (px: number) => px >= lo && px <= hi;
  if (snap.price.vwap !== null) lines.push({ y: r2(y(snap.price.vwap)), label: `VWAP ${fmtNum(snap.price.vwap)}`, kind: "vwap" });
  if (plan?.long) lines.push({ y: r2(y(plan.long.trigger)), label: `L trig ${plan.long.trigger}`, kind: "trigger" });
  if (plan?.short) lines.push({ y: r2(y(plan.short.trigger)), label: `S trig ${plan.short.trigger}`, kind: "trigger" });
  for (const l of levels) {
    if (!inRange(l.px)) continue;
    if (lines.some((x) => Math.abs(x.y - y(l.px)) < 0.5)) continue;
    lines.push({ y: r2(y(l.px)), label: `${l.name} ${l.px}`, kind: "level" });
  }
  lines.push({ y: r2(y(last)), label: `ES ${fmtNum(last)}`, kind: "price" });

  const timeLabels: { x: number; text: string }[] = [];
  const every = Math.max(1, Math.round(bars.length / 6));
  for (let i = 0; i < bars.length; i += every) timeLabels.push({ x: r2(4 + i * step + step / 2), text: fmtCt(bars[i].t) });

  return { width, priceH, deltaH, height: priceH + deltaH + 14, candles, deltaBars, deltaZeroY: r2(zeroY), lines, min: r2(lo), max: r2(hi), count: bars.length, timeLabels, plotRight, labelX: plotRight + 6 };
}