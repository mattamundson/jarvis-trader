// Server-only reader for the tape state directory (flow_snapshot.py + source producers write it).
// File names are a closed list; nothing request-controlled reaches the filesystem.
import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const TAPE_STATE_FILES = {
  flow: "flow-latest.json",
  gex: "gex-latest.json",
  doublewide: "doublewide-latest.json",
  aaron: "aaron-latest.json",
} as const;
export type TapeStateKey = keyof typeof TAPE_STATE_FILES;

export function tapeStateDir(env: NodeJS.ProcessEnv = process.env): string {
  const configured = (env.TAPE_STATE_DIR ?? "").trim();
  return configured || path.join(env.USERPROFILE || env.HOME || os.homedir(), "tape", "state");
}

export async function readTapeState(key: TapeStateKey, env: NodeJS.ProcessEnv = process.env): Promise<unknown> {
  try {
    return JSON.parse(await readFile(path.join(tapeStateDir(env), TAPE_STATE_FILES[key]), "utf8"));
  } catch {
    return null;
  }
}
