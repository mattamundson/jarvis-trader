// Item 3: read-only proof record (no writes).
import fs from "fs/promises";
import { SOURCE_LABELS } from "./sources";

export const PROOF_FILE = process.env.TAPE_PROOF_FILE || "C:\\Users\\mattm\\tape\\state\\proof-record.json";

export async function readProof() {
  try {
    const st = await fs.stat(PROOF_FILE);
    const j = JSON.parse(await fs.readFile(PROOF_FILE, "utf8"));
    return {
      ok: true,
      source: "proof-record.json (paper journal)",
      fileAgeS: Math.round((Date.now() - st.mtimeMs) / 1000),
      generated_ct: j.generated_ct ?? null,
      r_basis: j.r_basis ?? null,
      goal: j.goal_setups ?? 20,
      counted: j.counted ?? 0,
      avg_R: j.avg_R ?? null,
      total_R: j.total_R ?? null,
      wins: j.wins ?? null,
      losses: j.losses ?? null,
      setups: Array.isArray(j.setups) ? j.setups : [],
    };
  } catch (e) {
    return { ok: false, error: String((e as Error).message), source: SOURCE_LABELS.snapshot, setups: [] };
  }
}
