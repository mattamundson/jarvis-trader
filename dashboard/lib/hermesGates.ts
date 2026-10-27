// Hermes gates markdown bridge reader
import { promises as fs } from "node:fs";
import path from "node:path";

export interface HermesGate {
  name: string;
  status: "pass" | "warn" | "fail";
  detail?: string;
}

export interface HermesGatesReport {
  found: boolean;
  path?: string;
  gates: HermesGate[];
  fileLockout: boolean | null;
}

export function hermesGatesCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  const candidates: string[] = [];
  
  if (env.TAPE_STATE_DIR) {
    candidates.push(path.join(env.TAPE_STATE_DIR, "gates.md"));
  }
  
  const home = env.HOME || env.USERPROFILE;
  if (home) {
    candidates.push(path.join(home, ".jarvis", "gates.md"));
  }
  
  return candidates;
}

export function parseHermesGates(content: string): HermesGatesReport {
  const gates: HermesGate[] = [];
  const lines = content.split(/\r?\n/);
  let lockout: boolean | null = null;
  
  for (const line of lines) {
    const trimmed = line.trim();
    
    // Check for lockout line
    if (trimmed.startsWith("lockout:")) {
      const val = trimmed.substring(8).trim().toLowerCase();
      lockout = val === "on" || val === "true" || val === "active";
      continue;
    }
    
    // Parse gate lines starting with -
    if (trimmed.startsWith("-")) {
      const statusMatch = trimmed.match(/:\s*(pass|warn|fail)\s*$/i);
      if (statusMatch) {
        const status = statusMatch[1].toLowerCase() as "pass" | "warn" | "fail";
        const name = trimmed
          .substring(1)
          .replace(/:\s*(pass|warn|fail)\s*$/i, "")
          .trim();
        gates.push({ name, status });
      }
    }
  }
  
  return {
    found: gates.length > 0,
    gates,
    fileLockout: lockout,
  };
}

export async function readHermesGates(env: NodeJS.ProcessEnv = process.env): Promise<HermesGatesReport> {
  const candidates = hermesGatesCandidates(env);
  
  for (const candidatePath of candidates) {
    try {
      const content = await fs.readFile(candidatePath, "utf8");
      const report = parseHermesGates(content);
      if (report.found) {
        return { ...report, path: candidatePath };
      }
    } catch {
      // File doesn't exist or can't be read, try next candidate
      continue;
    }
  }
  
  return {
    found: false,
    gates: [],
    fileLockout: null,
  };
}
