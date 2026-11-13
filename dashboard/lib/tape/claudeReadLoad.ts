// Server-only reader. One fixed filename inside the tape state directory. No writes.
import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  CLAUDE_READ_FILE,
  findPrivateKeys,
  gammaFreshness,
  parseClaudeRead,
  claudeReadFreshness,
  type ClaudeReadPayload,
} from "@/lib/tape/claudeRead";

export type { ClaudeReadPayload };

const empty = (over: Pick<ClaudeReadPayload, "ok" | "missing" | "malformed" | "error">): ClaudeReadPayload => ({
  ...over,
  file: CLAUDE_READ_FILE,
  read: null,
  freshness: null,
  gamma: null,
});

/** ~/tape/state, or TAPE_STATE_DIR when set. On the trading PC that is C:\\Users\\mattm\\tape\\state. */
export function tapeStateDir(env: NodeJS.ProcessEnv = process.env): string {
  const configured = (env.TAPE_STATE_DIR ?? "").trim();
  if (configured) return configured;
  const home = env.USERPROFILE || env.HOME || os.homedir();
  return path.join(home, "tape", "state");
}

export async function loadClaudeRead(dir: string, nowMs: number): Promise<ClaudeReadPayload> {
  let text: string;
  try {
    text = await readFile(path.join(dir, CLAUDE_READ_FILE), "utf8");
  } catch {
    return empty({ ok: false, missing: true, malformed: false, error: "claude-read-latest.json is not in the tape state folder" });
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text.replace(/^\uFEFF/, ""));
  } catch {
    return empty({ ok: false, missing: false, malformed: true, error: "claude-read-latest.json is malformed JSON" });
  }
  const parsed = parseClaudeRead(raw);
  if (!parsed.ok) return empty({ ok: false, missing: false, malformed: true, error: parsed.error });
  if (findPrivateKeys(parsed.read).length > 0) {
    return empty({ ok: false, missing: false, malformed: true, error: "claude-read-latest.json failed the private-key check" });
  }
  const gamma = parsed.read.context.gamma
    ? { ...gammaFreshness(parsed.read.context.gamma.as_of, nowMs), present: true }
    : { present: false, asOf: null, asOfCt: null, ageMs: null, ageMinutes: null, stale: false, reason: "gamma not in this read" };
  return {
    ok: true,
    missing: false,
    malformed: false,
    error: null,
    file: CLAUDE_READ_FILE,
    read: parsed.read,
    freshness: claudeReadFreshness(parsed.read.written_at, nowMs),
    gamma,
  };
}
