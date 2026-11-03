// Item 4: plan card state from config/tape-plan.json + latest 1m series. Read-only.
import fs from "fs/promises";
import path from "path";

type Bar = { t: number; o?: number; h: number; l: number; c: number; delta?: number };
type Side = { trigger: number; stop: number; targets: number[]; minDelta?: number } | null;

export const VOID_AFTER_CT_MIN = 14 * 60; // 2:00 PM CT

function ctMinutes(epochS: number): number {
  const s = new Date(epochS * 1000).toLocaleString("en-US", { timeZone: "America/Chicago", hour12: false, hour: "2-digit", minute: "2-digit" });
  const [h, m] = s.split(":").map(Number);
  return (h % 24) * 60 + m;
}

function to5m(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (const b of bars) {
    const k = Math.floor(b.t / 300) * 300;
    const last = out[out.length - 1];
    if (last && last.t === k) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.delta = (last.delta ?? 0) + (b.delta ?? 0); }
    else out.push({ t: k, o: b.o, h: b.h, l: b.l, c: b.c, delta: b.delta ?? 0 });
  }
  return out;
}

export async function readPlanCard(flow: { series_1m?: Bar[]; price?: { last?: number }; nq?: { rel?: { last?: number } } } | null, nowS = Date.now() / 1000) {
  const file = process.env.TAPE_PLAN_FILE || path.join(process.cwd(), "config", "tape-plan.json");
  let plan: any;
  try { plan = JSON.parse(await fs.readFile(file, "utf8")); } catch (e) { return { ok: false, error: String((e as Error).message) }; }
  const bars = flow?.series_1m ?? [];
  const last = flow?.price?.last ?? bars[bars.length - 1]?.c ?? null;
  const nq = flow?.nq?.rel?.last ?? null;
  const all5 = to5m(bars);
  const closed5 = all5.filter((b) => b.t + 300 <= nowS);
  const lookback = (plan.lookbackMin ?? 90) * 60;
  const recent = closed5.filter((b) => b.t >= nowS - lookback);
  const pastVoid = ctMinutes(nowS) >= VOID_AFTER_CT_MIN;

  const side = (name: "long" | "short", s: Side) => {
    if (!s) return null;
    const isL = name === "long";
    const beyond = (px: number, lvl: number) => (isL ? px > lvl : px < lvl);
    const trigIdx = recent.findIndex((b) => beyond(b.c, s.trigger));
    const trigBar = trigIdx >= 0 ? recent[trigIdx] : null;
    const twoClose = recent.some((b, i) => i > 0 && beyond(b.c, s.trigger) && beyond(recent[i - 1].c, s.trigger));
    const after = trigBar ? bars.filter((b) => b.t >= trigBar.t) : [];
    const stopHit = after.some((b) => (isL ? b.l <= s.stop : b.h >= s.stop));
    const tgtHit = after.some((b) => s.targets.some((t) => (isL ? b.h >= t : b.l <= t)));
    const lastDelta = closed5[closed5.length - 1]?.delta ?? null;
    const gates = [
      { name: `5m close ${isL ? ">" : "<"} ${s.trigger}`, ok: !!trigBar },
      { name: `two 5m closes ${isL ? ">" : "<"} ${s.trigger}`, ok: twoClose },
      { name: `5m delta ${isL ? ">=" : "<="} ${isL ? "" : "-"}${s.minDelta ?? 0}`, ok: lastDelta !== null && (isL ? lastDelta >= (s.minDelta ?? 0) : lastDelta <= -(s.minDelta ?? 0)), value: lastDelta },
      { name: `NQ ${isL ? ">" : "<"} ${plan.nqRef ?? "?"}`, ok: nq !== null && plan.nqRef != null && (isL ? nq > plan.nqRef : nq < plan.nqRef), value: nq },
    ];
    let state: string = trigBar ? "TRIGGERED" : "ARMED";
    if (trigBar && stopHit) state = "STOPPED";
    else if (trigBar && tgtHit) state = "TARGET";
    if (!trigBar && pastVoid) state = "VOID (after 2:00 PM CT)";
    return { side: name, trigger: s.trigger, stop: s.stop, targets: s.targets, gates, state, triggeredAt: trigBar?.t ?? null, distance: last !== null ? +(last - s.trigger).toFixed(2) : null };
  };
  return {
    ok: true,
    date: plan.date ?? null,
    note: plan.note ?? null,
    planIsToday: plan.date === new Date(nowS * 1000).toLocaleDateString("en-CA", { timeZone: "America/Chicago" }),
    last,
    pastVoid,
    legs: [side("long", plan.long ?? null), side("short", plan.short ?? null)].filter(Boolean),
  };
}
