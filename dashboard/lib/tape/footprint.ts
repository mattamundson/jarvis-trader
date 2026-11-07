// Item 5: 5m footprint (bid/ask volume per price + bar delta) and multi-day
// composite volume/TPO profile, parsed read-only from es_tick_recorder CSVs.
// Engine endpoints on 8010 need an API key, so tick files are the source.
import fs from "fs";
import fsp from "fs/promises";
import path from "path";
import readline from "readline";

export const TICK_DIR = process.env.TAPE_TICK_DIR || "C:\\Users\\mattm\\es_tick_recorder\\data";
export const FOOTPRINT_SOURCE = "es_tick_recorder tick CSV (IB live read-only 4001)";

type Lvl = { bid: number; ask: number };
type Agg = {
  offset: number; size: number; mtimeMs: number; partial: string;
  bars: Map<number, { t: number; o: number; h: number; l: number; c: number; delta: number; levels: Map<number, Lvl> }>;
  prof: Map<number, number>; tpo: Map<number, Set<number>>;
};
const cache = new Map<string, Agg>();
// Per-file single-flight (PR #1013 review 4503369536): concurrent loadFile()
// calls for the same file share one ingest pass. Without this, every caller
// that arrived mid-stream saw the cache's pre-offset-advance Agg and
// re-ingested the same bytes (one 10-lot became 40 under Promise.all).
const inflight = new Map<string, Promise<Agg | null>>();

function blank(): Agg { return { offset: 0, size: 0, mtimeMs: 0, partial: "", bars: new Map(), prof: new Map(), tpo: new Map() }; }

function ingest(a: Agg, line: string) {
  const f = line.split(",");
  if (f.length < 8 || f[0] === "ts_utc") return;
  const t = Date.parse(f[0]) / 1000; const px = +f[2]; const sz = +f[3]; const side = f[6];
  if (!isFinite(t) || !isFinite(px) || !isFinite(sz)) return;
  const k = Math.floor(t / 300) * 300;
  let b = a.bars.get(k);
  if (!b) { b = { t: k, o: px, h: px, l: px, c: px, delta: 0, levels: new Map() }; a.bars.set(k, b); }
  b.h = Math.max(b.h, px); b.l = Math.min(b.l, px); b.c = px;
  let lv = b.levels.get(px); if (!lv) { lv = { bid: 0, ask: 0 }; b.levels.set(px, lv); }
  if (side === "A") { lv.ask += sz; b.delta += sz; } else if (side === "B") { lv.bid += sz; b.delta -= sz; }
  a.prof.set(px, (a.prof.get(px) ?? 0) + sz);
  const p30 = Math.floor(t / 1800);
  let s = a.tpo.get(px); if (!s) { s = new Set(); a.tpo.set(px, s); } s.add(p30);
}

async function loadFileInner(file: string): Promise<Agg | null> {
  let st; try { st = await fsp.stat(file); } catch { return null; }
  let a = cache.get(file);
  if (!a || st.size < a.offset) { a = blank(); cache.set(file, a); }
  if (st.size === a.offset) return a;
  const stream = fs.createReadStream(file, { start: a.offset, end: st.size - 1, encoding: "utf8" });
  let buf = a.partial;
  for await (const chunk of stream) {
    buf += chunk;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) { ingest(a, buf.slice(0, i).trim()); buf = buf.slice(i + 1); }
  }
  a.partial = buf; a.offset = st.size; a.size = st.size; a.mtimeMs = st.mtimeMs;
  return a;
}

// Single-flight wrapper: only one ingest per file runs at a time; concurrent
// callers await the same promise, so bytes are ingested exactly once and the
// published Agg is always fully caught up to its recorded offset.
function loadFile(file: string): Promise<Agg | null> {
  const running = inflight.get(file);
  if (running) return running;
  const p = loadFileInner(file).finally(() => {
    if (inflight.get(file) === p) inflight.delete(file);
  });
  inflight.set(file, p);
  return p;
}

// PR #1013 review 4503369563: sort by the date suffix, not the full filename.
// Lexical order breaks across contract rollover (ESH7_20261215 vs ESZ6_202611*).
function fileDate(name: string): string { return name.slice(-12, -4); }
function byDateDesc(a: string, b: string): number {
  return fileDate(b).localeCompare(fileDate(a)) || b.localeCompare(a);
}

function ctDate(d: Date) { return d.toLocaleDateString("en-CA", { timeZone: "America/Chicago" }).replace(/-/g, ""); }

export async function readFootprint(maxBars = 12) {
  const files = (await fsp.readdir(TICK_DIR).catch(() => [] as string[])).filter((n) => /^ES[A-Z]\d_\d{8}\.csv$/.test(n)).sort(byDateDesc);
  if (!files.length) return { ok: false, error: "no tick CSVs", source: FOOTPRINT_SOURCE };
  const today = ctDate(new Date());
  const latest = files.filter((n) => n.includes(today)).shift() ?? files[0];
  const a = await loadFile(path.join(TICK_DIR, latest));
  if (!a) return { ok: false, error: "read failed", source: FOOTPRINT_SOURCE };
  const bars = [...a.bars.values()].sort((x, y) => x.t - y.t).slice(-maxBars).map((b) => ({
    t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, delta: b.delta,
    levels: [...b.levels.entries()].sort((x, y) => y[0] - x[0]).map(([px, v]) => ({ px, bid: v.bid, ask: v.ask, delta: v.ask - v.bid })),
  }));
  return { ok: true, source: FOOTPRINT_SOURCE, file: latest, isToday: latest.includes(today), fileAgeS: Math.round((Date.now() - a.mtimeMs) / 1000), bars };
}

export async function readCompositeProfile(days = 4, bucket = 1) {
  const files = (await fsp.readdir(TICK_DIR).catch(() => [] as string[])).filter((n) => /^ES[A-Z]\d_\d{8}\.csv$/.test(n)).sort(byDateDesc).slice(0, days);
  const vol = new Map<number, number>();
  // PR #1013 review 4503369558: TPO per bucket is the UNION of period IDs
  // (30-min epoch buckets) touched at any price in the bucket, not the sum of
  // per-price set sizes -- the same half-hour at 100 and 100.25 counts once.
  const tpoSets = new Map<number, Set<number>>();
  for (const n of files) {
    const a = await loadFile(path.join(TICK_DIR, n)); if (!a) continue;
    for (const [px, v] of a.prof) { const k = Math.floor(px / bucket) * bucket; vol.set(k, (vol.get(k) ?? 0) + v); }
    for (const [px, s] of a.tpo) {
      const k = Math.floor(px / bucket) * bucket;
      let u = tpoSets.get(k); if (!u) { u = new Set(); tpoSets.set(k, u); }
      for (const period of s) u.add(period);
    }
  }
  const tpo = new Map<number, number>();
  for (const [k, u] of tpoSets) tpo.set(k, u.size);
  const rows = [...vol.entries()].sort((x, y) => y[0] - x[0]).map(([px, v]) => ({ px, vol: v, tpo: tpo.get(px) ?? 0 }));
  const total = rows.reduce((s, r) => s + r.vol, 0);
  let poc = rows.reduce((m, r) => (r.vol > (m?.vol ?? -1) ? r : m), rows[0] ?? null);
  // 70% value area around POC
  let vah = poc?.px ?? null, val = poc?.px ?? null;
  if (poc) {
    const asc = [...rows].sort((x, y) => x.px - y.px); let i = asc.findIndex((r) => r.px === poc!.px), lo = i, hi = i, acc = poc.vol;
    while (acc < total * 0.7 && (lo > 0 || hi < asc.length - 1)) {
      const up = hi < asc.length - 1 ? asc[hi + 1].vol : -1, dn = lo > 0 ? asc[lo - 1].vol : -1;
      if (up >= dn) { hi++; acc += up; } else { lo--; acc += dn; }
    }
    vah = asc[hi].px; val = asc[lo].px;
  }
  return { ok: rows.length > 0, source: FOOTPRINT_SOURCE, days: files, bucket, poc: poc?.px ?? null, vah, val, totalVol: total, rows };
}
