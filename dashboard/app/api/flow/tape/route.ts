import { NextResponse } from "next/server";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { currentGlobexTradingDate, esMarketState } from "@/lib/marketSession";

/**
 * Read-only local readout of the recorder snapshot for the /tape screen.
 * Primary: TAPE_FLOW_FILE (the PC recorder's flow-latest.json). Fallback: the box export copied to
 * TAPE_FLOW_FALLBACK_FILE (state\box\flow-latest.json) when the primary is older than 10 min and
 * the fallback is newer. Same for gex. Every block carries a `source` label. Never throws.
 */
export const dynamic = "force-dynamic";

const STATE = "C:\\Users\\mattm\\tape\\state";
const DEFAULT_FILE = path.join(STATE, "flow-latest.json");
const DEFAULT_FALLBACK = path.join(STATE, "box", "flow-latest.json");
const DEFAULT_GEX_FILE = path.join(STATE, "gex-latest.json");
const DEFAULT_GEX_FALLBACK = path.join(STATE, "box", "gex-latest.json");
const HEADERS = { "Cache-Control": "no-store" };
const STALE_AFTER_MS = 10 * 60 * 1000;

const PORT_LABEL: Record<number, string> = { 4002: "IB paper 4002", 4001: "IB live read-only 4001" };

async function readJson(file: string): Promise<{ raw: any; mtimeMs: number } | null> {
  try {
    const [txt, st] = await Promise.all([readFile(file, "utf8"), stat(file)]);
    return { raw: JSON.parse(txt.replace(/^\uFEFF/, "")), mtimeMs: st.mtimeMs };
  } catch {
    return null;
  }
}

/** Prefer primary; use fallback only if primary is missing/stale and fallback is newer. */
async function pick(primary: string, fallback: string, now: number) {
  const p = await readJson(primary);
  if (p && now - p.mtimeMs <= STALE_AFTER_MS) return { ...p, file: "primary" as const };
  const f = await readJson(fallback);
  if (f && (!p || f.mtimeMs > p.mtimeMs)) return { ...f, file: "box-fallback" as const };
  return p ? { ...p, file: "primary" as const } : null;
}

async function readPlan(): Promise<{ plan: unknown; planError: string | null }> {
  const file = process.env.TAPE_PLAN_FILE || path.join(process.cwd(), "config", "tape-plan.json");
  try {
    return { plan: JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/, "")), planError: null };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unreadable";
    return { plan: null, planError: `plan unreadable: ${msg.slice(0, 120)}` };
  }
}

/**
 * Recorder liveness block passed through verbatim from the flow snapshot. `lastTickAgeS` is the
 * age of the last ACTUAL tick (recorder's own last_tick_age_s plus the file's age since it was
 * written) — deliberately separate from heartbeat/file age, so a 5s heartbeat write can never
 * make an absent or stale tick look current.
 */
function recorderBlock(raw: any, fileAgeS: number | null) {
  const r = raw?.recorder && typeof raw.recorder === "object" ? raw.recorder : {};
  const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const lastTickAgeS = num(r.last_tick_age_s) === null ? null : num(r.last_tick_age_s)! + (fileAgeS ?? 0);
  return {
    state: typeof r.state === "string" ? r.state : null,
    heartbeatAgeS: num(r.heartbeat_age_s),
    lastTickAgeS: lastTickAgeS === null ? null : Math.round(lastTickAgeS * 10) / 10,
    reconnects: num(r.reconnects),
    connectedPort: num(r.connected_port),
    sessionTradingDay: typeof raw?.session?.trading_day === "string" ? raw.session.trading_day : null,
    levelsSource: typeof raw?.levels_source === "string" ? raw.levels_source : null,
  };
}

function flowSource(raw: any, which: string): string {
  if (typeof raw?.source === "string" && raw.source) return which === "box-fallback" ? `${raw.source} (box fallback)` : raw.source;
  const port = Number(raw?.recorder?.connected_port);
  return PORT_LABEL[port] ?? "unknown";
}

export async function GET() {
  const serverEpochMs = Date.now();
  const { plan, planError } = await readPlan();
  const marketState = esMarketState(serverEpochMs);
  const globexTradingDate = currentGlobexTradingDate(serverEpochMs);
  const todayCt = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(serverEpochMs));
  const g = await pick(process.env.TAPE_GEX_FILE || DEFAULT_GEX_FILE, process.env.TAPE_GEX_FALLBACK_FILE || DEFAULT_GEX_FALLBACK, serverEpochMs);
  const gex = g
    ? { asof_ct: g.raw.asof_ct ?? null, pulled_ct: g.raw.pulled_ct ?? null, flip: g.raw.flip ?? null, call_wall: g.raw.call_wall ?? null, put_wall: g.raw.put_wall ?? null, max_pain: g.raw.max_pain ?? null, net_gex: g.raw.net_gex ?? null, source: g.raw.source ?? "ZeroGEX", fetch_ok: g.raw.fetch_ok ?? null, file: g.file, file_age_s: Math.round((serverEpochMs - g.mtimeMs) / 1000), stale: serverEpochMs - g.mtimeMs > STALE_AFTER_MS }
    : null;
  const gexError = g ? null : "gex file unreadable";
  const f = await pick(process.env.TAPE_FLOW_FILE || DEFAULT_FILE, process.env.TAPE_FLOW_FALLBACK_FILE || DEFAULT_FALLBACK, serverEpochMs);
  if (!f) {
    return NextResponse.json({ ok: false, serverEpochMs, todayCt, globexTradingDate, marketState, recorder: null, gex, gexError, error: "flow file unreadable" }, { status: 200, headers: HEADERS });
  }
  const raw = f.raw;
  const nq = raw?.nq ? { rel: raw.nq.rel ?? null, status: raw.nq.status ?? null } : null;
  const fileAgeS = Math.round((serverEpochMs - f.mtimeMs) / 1000);
  return NextResponse.json(
    {
      ok: true,
      serverEpochMs,
      todayCt,
      globexTradingDate,
      marketState,
      plan,
      planError,
      recorder: recorderBlock(raw, fileAgeS),
      gex,
      gexError,
      source: flowSource(raw, f.file),
      sourceBars: raw.source_bars ?? null,
      file: f.file,
      fileAgeS,
      stale10m: fileAgeS * 1000 > STALE_AFTER_MS,
      snapshot: {
        as_of_epoch: raw.as_of_epoch ?? null,
        as_of_ct: raw.as_of_ct ?? null,
        price: raw.price ?? null,
        cvd: raw.cvd ?? null,
        gate_cvd: raw.gate_cvd ?? null,
        nq,
        levels: raw.levels ?? [],
        series_1m: raw.series_1m ?? [],
      },
    },
    { headers: HEADERS },
  );
}
