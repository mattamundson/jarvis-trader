import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * Read-only local readout of the recorder snapshot for the /tape screen.
 * Reads TAPE_FLOW_FILE (default: the recorder's flow-latest.json) and the trigger plan
 * (TAPE_PLAN_FILE, default config/tape-plan.json) on every request, no cache.
 * Only whitelisted market fields are returned. Never throws; failures come back as { ok: false }.
 * A missing or broken plan does not break the readout: plan is null and planError says why.
 */
export const dynamic = "force-dynamic";

const DEFAULT_FILE = "C:\\Users\\mattm\\tape\\state\\flow-latest.json";
const HEADERS = { "Cache-Control": "no-store" };

async function readPlan(): Promise<{ plan: unknown; planError: string | null }> {
  const file = process.env.TAPE_PLAN_FILE || path.join(process.cwd(), "config", "tape-plan.json");
  try {
    return { plan: JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/, "")), planError: null };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unreadable";
    return { plan: null, planError: `plan unreadable: ${msg.slice(0, 120)}` };
  }
}

const DEFAULT_GEX_FILE = "C:\\Users\\mattm\\tape\\state\\gex-latest.json";

/** Gamma levels from the ZeroGEX snapshot. Never throws: missing file gives { gex: null, gexError }. */
async function readGex(): Promise<{ gex: unknown; gexError: string | null }> {
  const file = process.env.TAPE_GEX_FILE || DEFAULT_GEX_FILE;
  try {
    const r = JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/, ""));
    return {
      gex: { asof_ct: r.asof_ct ?? null, pulled_ct: r.pulled_ct ?? null, flip: r.flip ?? null, call_wall: r.call_wall ?? null, put_wall: r.put_wall ?? null, max_pain: r.max_pain ?? null, net_gex: r.net_gex ?? null, source: r.source ?? null, fetch_ok: r.fetch_ok ?? null },
      gexError: null,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unreadable";
    return { gex: null, gexError: `gex file unreadable: ${msg.slice(0, 120)}` };
  }
}

export async function GET() {
  const { gex, gexError } = await readGex();
  const serverEpochMs = Date.now();
  const file = process.env.TAPE_FLOW_FILE || DEFAULT_FILE;
  const { plan, planError } = await readPlan();
  try {
    const raw = JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/, ""));
    const nq = raw?.nq ? { rel: raw.nq.rel ?? null, status: raw.nq.status ?? null } : null;
    return NextResponse.json(
      {
        ok: true,
        serverEpochMs,
        plan,
        planError,
        gex,
        gexError,
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
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unreadable";
    return NextResponse.json(
      { ok: false, serverEpochMs, gex, gexError, error: `flow file unreadable: ${msg.slice(0, 120)}` },
      { status: 200, headers: HEADERS },
    );
  }
}