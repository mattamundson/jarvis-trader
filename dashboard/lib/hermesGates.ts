import { access, readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

export type HermesGateStatus = "pass" | "fail" | "warn" | "unknown";

export interface HermesGate {
  name: string;
  status: HermesGateStatus;
}

export interface HermesGatesReport {
  found: boolean;
  message: string;
  gates: HermesGate[];
  fileLockout: boolean | null;
}

const STATUS_WORDS: Record<string, HermesGateStatus> = {
  pass: "pass",
  passed: "pass",
  ok: "pass",
  clear: "pass",
  open: "pass",
  fail: "fail",
  failed: "fail",
  blocked: "fail",
  lock: "fail",
  locked: "fail",
  warn: "warn",
  warning: "warn",
};

function normalizeStatus(raw: string): HermesGateStatus {
  return STATUS_WORDS[raw.trim().toLowerCase()] ?? "unknown";
}

function lockoutValue(raw: string): boolean | null {
  const value = raw.trim().toLowerCase();
  if (["on", "true", "locked", "active", "yes", "halted"].includes(value)) return true;
  if (["off", "false", "clear", "inactive", "no", "open"].includes(value)) return false;
  return null;
}

/**
 * Read gate rows Hermes actually wrote. Checkbox lines and `name: status`
 * lines are gates. Anything else is ignored so the page cannot invent names.
 */
export function parseHermesGates(markdown: string): Pick<HermesGatesReport, "gates" | "fileLockout"> {
  const gates: HermesGate[] = [];
  let fileLockout: boolean | null = null;

  for (const line of markdown.split(/\r?\n/)) {
    const lock = line.match(/^\s*lockout\s*:\s*(.+?)\s*$/i);
    if (lock) {
      const parsed = lockoutValue(lock[1]);
      if (parsed !== null) fileLockout = parsed;
      continue;
    }

    const box = line.match(/^\s*[-*]\s+\[(x|X| )\]\s+(.+?)\s*$/);
    if (box) {
      const name = box[2].trim();
      if (name) gates.push({ name, status: box[1].toLowerCase() === "x" ? "pass" : "fail" });
      continue;
    }

    const kv = line.match(/^\s*[-*]?\s*([^:#]{1,80}?)\s*:\s*([A-Za-z][A-Za-z_-]{1,20})\s*$/);
    if (!kv) continue;
    const name = kv[1].trim();
    if (!name || /^lockout$/i.test(name)) continue;
    const status = normalizeStatus(kv[2]);
    if (status === "unknown") continue;
    gates.push({ name, status });
  }

  return { gates, fileLockout };
}

export function hermesGatesCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  const home = env.USERPROFILE || env.HOME || os.homedir();
  const configured = (env.HERMES_GATES_PATH ?? "").trim();
  return [
    configured,
    path.join(home, ".hermes", "gates.md"),
    path.join(home, "AppData", "Local", "hermes", "gates.md"),
    path.join(home, "AppData", "Local", "hermes", "profiles", "default", "gates.md"),
  ].filter((candidate) => candidate.length > 0);
}

function isGatesFile(candidate: string): boolean {
  return path.basename(candidate).toLowerCase() === "gates.md";
}

export async function readHermesGates(
  env: NodeJS.ProcessEnv = process.env,
): Promise<HermesGatesReport> {
  for (const candidate of hermesGatesCandidates(env)) {
    if (!isGatesFile(candidate)) continue;
    try {
      await access(candidate);
    } catch {
      continue;
    }
    const markdown = await readFile(candidate, "utf8");
    const parsed = parseHermesGates(markdown);
    return {
      found: true,
      message: parsed.gates.length > 0 ? "hermes gates" : "gates file found, no gate lines",
      gates: parsed.gates,
      fileLockout: parsed.fileLockout,
    };
  }

  return {
    found: false,
    message: "gates file missing",
    gates: [],
    fileLockout: null,
  };
}
