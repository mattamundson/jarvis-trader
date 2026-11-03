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

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const STATE = process.env.TAPE_STATE_DIR || "C:\\Users\\mattm\\tape\\state";

async function snapshot() {
  const base = process.env.TAPE_SNAPSHOT_BASE_URL;
  try {
    if (base) {
      const r = await fetch(`${base.replace(/\/$/, "")}/tape-extras.json`, { cache: "no-store" });
      if (r.ok) return { ...(await r.json()), snapshotMode: true };
    }
    const j = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "tape-snapshots", "tape-extras.json"), "utf8"));
    return { ...j, snapshotMode: true };
  } catch (e) {
    return { snapshotMode: true, error: `no snapshot: ${(e as Error).message}` };
  }
}

async function readJson(file: string) {
  try { const st = await fs.stat(file); return { j: JSON.parse(await fs.readFile(file, "utf8")), ageS: Math.round((Date.now() - st.mtimeMs) / 1000) }; } catch { return null; }
}

export async function GET() {
  if (process.env.TAPE_SNAPSHOT_MODE === "1") return NextResponse.json(await snapshot(), { headers: { "cache-control": "no-store" } });
  const flow = await readJson(path.join(STATE, "flow-latest.json"));
  const gex = await readJson(path.join(STATE, "gex-latest.json"));
  const [proof, plan, footprint, profile, ib, footprintWide, profileToday] = await Promise.all([
    readProof(),
    readPlanCard(flow?.j ?? null),
    readFootprint().catch((e) => ({ ok: false, error: String(e) })),
    readCompositeProfile().catch((e) => ({ ok: false, error: String(e) })),
    readIbStatus().catch((e) => ({ ok: false, light: "red", error: String(e), checks: [] })),
    readFootprint(36).catch((e) => ({ ok: false, error: String(e) })),
    readCompositeProfile(1).catch((e) => ({ ok: false, error: String(e) })),
  ]);
  // Chart overlays (addition): VWAP/last from flow-latest, plan levels from config/tape-plan.json.
  const chart: any = { vwap: flow?.j?.price?.vwap ?? null, last: flow?.j?.price?.last ?? null, levels: [] as any[], levelsSource: "config/tape-plan.json" };
  try {
    const tp = JSON.parse(await fs.readFile(process.env.TAPE_PLAN_FILE || path.join(process.cwd(), "config", "tape-plan.json"), "utf8"));
    for (const side of ["long", "short"] as const) {
      const s = tp?.[side]; if (!s) continue;
      const S = side === "long" ? "Long" : "Short";
      if (s.trigger != null) chart.levels.push({ name: `${S} trigger`, px: s.trigger, kind: "trigger" });
      if (s.stop != null) chart.levels.push({ name: `${S} stop`, px: s.stop, kind: "invalid" });
      (s.targets ?? []).forEach((t: number, i: number) => chart.levels.push({ name: `${S} T${i + 1}`, px: t, kind: "target" }));
    }
    // Static plan VWAP refs are labelled as such so they are never confused with the live VWAP line.
    for (const l of tp?.extraLevels ?? []) if (typeof l?.px === "number") chart.levels.push(/vwap/i.test(String(l.name)) ? { name: `plan ref: ${l.name}`, px: l.px, kind: "planref" } : { name: l.name, px: l.px, kind: "level" });
  } catch {}
  const flowSrc = normalizeSource(flow?.j?.source, flow?.j?.recorder?.connected_port);
  chart.priceSource = flowSrc; chart.priceAgeS = flow?.ageS ?? null;
  // GEX overlays (addition): flip / walls / pin from gex-latest, labelled with source + snapshot age.
  if (gex?.j) {
    const gAge = typeof gex.j.age_min === "number" ? gex.j.age_min + Math.round((gex.ageS ?? 0) / 60) : null;
    const tag = `ZeroGEX ${gAge != null ? gAge + "m" : "age ?"}${gex.j.stale || gex.j.fetch_ok === false ? " STALE" : ""}`;
    for (const [k, n] of [["flip", "γ flip"], ["call_wall", "call wall"], ["put_wall", "put wall"], ["pin", "pin"]] as const)
      if (typeof gex.j[k] === "number") chart.levels.push({ name: `${n} · ${tag}`, px: gex.j[k], kind: "gex" });
    chart.gex = { source: gex.j.source ?? "ZeroGEX", asofCt: gex.j.asof_ct ?? null, ageMin: gAge, stale: !!gex.j.stale };
  }
  const sources = {
    labels: SOURCE_LABELS,
    tape: { source: flowSrc, ageS: flow?.ageS ?? null },
    gex: { source: gex?.j?.source ?? gex?.j?.provider ?? "unknown", ageS: gex?.ageS ?? null },
    plan: { source: flowSrc },
    footprint: { source: (footprint as any).source ?? null },
    profile: { source: (profile as any).source ?? null },
    proof: { source: (proof as any).source ?? null },
  };
  return NextResponse.json({ generatedAt: Date.now(), snapshotMode: false, sources, proof, plan, footprint, profile, ib, footprintWide, profileToday, chart }, { headers: { "cache-control": "no-store" } });
}
