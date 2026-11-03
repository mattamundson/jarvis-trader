// /tape extras (items 2-6): source labels, proof record, plan card, footprint,
// composite profile, IB paper status light. GET only; no engine writes, no orders.
import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { normalizeSource, SOURCE_LABELS } from "@/lib/tape/sources";
import { readProof } from "@/lib/tape/proof";
import { readPlanCard } from "@/lib/tape/planCard";
import { readFootprint, readCompositeProfile } from "@/lib/tape/footprint";
import { readIbStatus } from "@/lib/tape/ibStatus";
import { isSnapshotMode, tapeExtrasSnapshot } from "@/lib/tape/snapshotMode";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const STATE = process.env.TAPE_STATE_DIR || "C:\\Users\\mattm\\tape\\state";

async function readJson(file: string) {
  try { const st = await fs.stat(file); return { j: JSON.parse(await fs.readFile(file, "utf8")), ageS: Math.round((Date.now() - st.mtimeMs) / 1000) }; } catch { return null; }
}

export async function GET() {
  if (isSnapshotMode()) return NextResponse.json(tapeExtrasSnapshot(), { headers: { "cache-control": "no-store" } });
  const flow = await readJson(path.join(STATE, "flow-latest.json"));
  const gex = await readJson(path.join(STATE, "gex-latest.json"));
  const [proof, plan, footprint, profile, ib] = await Promise.all([
    readProof(),
    readPlanCard(flow?.j ?? null),
    readFootprint().catch((e) => ({ ok: false, error: String(e) })),
    readCompositeProfile().catch((e) => ({ ok: false, error: String(e) })),
    readIbStatus().catch((e) => ({ ok: false, light: "red", error: String(e), checks: [] })),
  ]);
  const flowSrc = normalizeSource(flow?.j?.source, flow?.j?.recorder?.connected_port);
  const sources = {
    labels: SOURCE_LABELS,
    tape: { source: flowSrc, ageS: flow?.ageS ?? null },
    gex: { source: gex?.j?.source ?? gex?.j?.provider ?? "unknown", ageS: gex?.ageS ?? null },
    plan: { source: flowSrc },
    footprint: { source: (footprint as any).source ?? null },
    profile: { source: (profile as any).source ?? null },
    proof: { source: (proof as any).source ?? null },
  };
  return NextResponse.json({ generatedAt: Date.now(), snapshotMode: false, sources, proof, plan, footprint, profile, ib }, { headers: { "cache-control": "no-store" } });
}
