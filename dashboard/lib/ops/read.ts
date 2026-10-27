import { readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { OPS_FILES, buildOpsSnapshot, type OpsFileKey, type OpsMeta, type OpsSnapshot, type OpsTexts } from "@/lib/ops/snapshot";

/**
 * Read-only loader for the Hermes record. Server only: import it from a server component, never from a
 * client component, and never from any of the tape code.
 *
 * Directory: OPS_HERMES_DIR, else the first of ~/tape/hermes, ~/tape/risk-os that holds the ladder tracker.
 * Hermes writes these files on its own sandbox; this directory is where they are mirrored on this machine.
 */

const MAX_BYTES = 3 * 1024 * 1024;

export function candidateDirs(env: NodeJS.ProcessEnv = process.env): string[] {
  if (env.OPS_HERMES_DIR) return [env.OPS_HERMES_DIR];
  const home = os.homedir();
  return [path.join(home, "tape", "hermes"), path.join(home, "tape", "risk-os")];
}

async function exists(p: string): Promise<boolean> {
  try { await stat(p); return true; } catch { return false; }
}

export async function resolveOpsDir(env: NodeJS.ProcessEnv = process.env): Promise<string | null> {
  for (const d of candidateDirs(env)) if (await exists(path.join(d, OPS_FILES.tracker))) return d;
  return null;
}

export async function loadOpsSnapshot(now: Date = new Date(), env: NodeJS.ProcessEnv = process.env): Promise<OpsSnapshot> {
  const dir = await resolveOpsDir(env);
  const texts: OpsTexts = {};
  const meta: OpsMeta = {};
  if (dir) {
    for (const key of Object.keys(OPS_FILES) as OpsFileKey[]) {
      const file = path.join(dir, OPS_FILES[key]);
      try {
        const st = await stat(file);
        if (!st.isFile() || st.size > MAX_BYTES) continue;
        texts[key] = (await readFile(file, "utf8")).replace(/^\uFEFF/, "");
        meta[key] = { bytes: st.size, mtimeMs: st.mtimeMs };
      } catch { /* missing file: reported as not found */ }
    }
  }
  return buildOpsSnapshot(texts, meta, now, dir ? path.basename(path.dirname(dir)) + "/" + path.basename(dir) : null);
}
