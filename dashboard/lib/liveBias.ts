/** Live, fluid bias vote. Recomputed every poll from the flow + gex snapshots; independent of the plan file. */
export type Vote = "up" | "down" | "flat" | "n/a";
export interface BiasInput { name: string; vote: Vote; detail: string }
export interface LiveBias { bias: "BULL" | "BEAR" | "MIXED"; inputs: BiasInput[]; gamma: { sign: "long" | "short" | "n/a"; netGex: number | null; raw: string | null; note: string } }

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
/** net_gex arrives as a number or a string like "-2.06B" / "614M". */
function parseGex(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  const m = v.trim().match(/^([+-]?\d+(?:\.\d+)?)\s*([KMB])?$/i);
  if (!m) return null;
  const mult = { K: 1e3, M: 1e6, B: 1e9 }[(m[2] ?? "").toUpperCase() as "K" | "M" | "B"] ?? 1;
  return Number(m[1]) * mult;
}
const sgn = (n: number | null): Vote => (n === null ? "n/a" : n > 0 ? "up" : n < 0 ? "down" : "flat");

export function liveBias(args: { last: number | null; vwap: number | null; gateCvd: unknown; nqRel: unknown; netGex: unknown }): LiveBias {
  const inputs: BiasInput[] = [];
  const { last, vwap } = args;
  const d = last !== null && vwap !== null ? last - vwap : null;
  inputs.push({ name: "Price vs VWAP", vote: sgn(d), detail: d === null ? "n/a" : `${last} vs ${vwap} (${d >= 0 ? "+" : ""}${d.toFixed(2)})` });

  const g = (args.gateCvd ?? {}) as Record<string, unknown>;
  const z = num(g.z);
  const c30 = num(g.cvd30);
  const cv = z ?? c30;
  inputs.push({ name: "CVD 30m", vote: sgn(cv), detail: z !== null ? `z30 ${z >= 0 ? "+" : ""}${z.toFixed(2)}` : c30 !== null ? `cvd30 ${c30}` : "n/a" });

  const rel = (args.nqRel ?? {}) as { windows?: Record<string, { rs?: unknown }> };
  const rs = num(rel.windows?.["30m"]?.rs);
  inputs.push({ name: "NQ rel strength 30m", vote: sgn(rs), detail: rs === null ? "n/a" : `rs ${rs >= 0 ? "+" : ""}${rs.toFixed(3)}%` });

  const ng = parseGex(args.netGex);
  const gamma: LiveBias["gamma"] =
    ng === null
      ? { sign: "n/a", netGex: null, raw: null, note: "gamma n/a" }
      : ng >= 0
        ? { sign: "long", netGex: ng, raw: String(args.netGex), note: "long gamma: dealers damp moves, fades favored" }
        : { sign: "short", netGex: ng, raw: String(args.netGex), note: "short gamma: moves can run" };

  const votes = inputs.map((i) => i.vote);
  const bias = votes.every((v) => v === "up") ? "BULL" : votes.every((v) => v === "down") ? "BEAR" : "MIXED";
  return { bias, inputs, gamma };
}

export function todayCT(nowMs = Date.now()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(nowMs));
}
