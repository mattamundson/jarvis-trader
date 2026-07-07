import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

// Server-side (Node runtime) route that reads LOCAL environment-fleet state:
//   <JARVIS_HOME>/.claude/loops/registry.json          — loop fleet registry
//   <JARVIS_HOME>/.claude/loops/env-canary/report-latest.md — daily canary verdict
// JARVIS_HOME defaults to C:\Users\mattm. This is local-machine observability
// only — nothing here touches the engine or carries credentials.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface RegistryLoop {
  id: string;
  schedule?: string;
  status?: string;
  last_heartbeat?: string | null;
  runner?: string;
}

interface FleetLoop {
  id: string;
  status: string;
  runner: string;
  schedule: string;
  last_heartbeat: string | null;
  color: "GREEN" | "RED" | "ERROR" | "UNKNOWN";
  stale: boolean;
}

interface CanaryReport {
  overall: "GREEN" | "RED" | "UNKNOWN";
  failing: string[];
  generated_at: string | null;
}

function jarvisHome(): string {
  return process.env.JARVIS_HOME ?? "C:\\Users\\mattm";
}

/** Parse a registry `schedule` string into a cadence in hours (null = no cadence). */
function cadenceHours(schedule: string | undefined): number | null {
  if (!schedule) return null;
  const s = schedule.toUpperCase();
  // Most specific first
  const everyMin = s.match(/EVERY-(\d+)-MIN/);
  if (everyMin) return Number(everyMin[1]) / 60;
  const minSlash = s.match(/MIN\/(\d+)/);
  if (minSlash) return Number(minSlash[1]) / 60;
  const minute = s.match(/MINUTE:(\d+)/);
  if (minute) return Number(minute[1]) / 60;
  if (s.includes("HOURLY")) return 1;
  if (s.includes("WEEKLY")) return 7 * 24;
  if (s.includes("DAILY")) return 24;
  return null;
}

/** Registry heartbeat format: "2026-07-06T22:23:23Z GREEN" (timestamp + color). */
function parseHeartbeat(hb: string | null | undefined): {
  ts: number | null;
  color: FleetLoop["color"];
} {
  if (!hb) return { ts: null, color: "UNKNOWN" };
  const parts = hb.trim().split(/\s+/);
  const ts = new Date(parts[0]).getTime();
  const colorRaw = (parts[1] ?? "").toUpperCase();
  const color: FleetLoop["color"] =
    colorRaw === "GREEN" || colorRaw === "RED" || colorRaw === "ERROR" ? colorRaw : "UNKNOWN";
  return { ts: Number.isNaN(ts) ? null : ts, color };
}

async function readRegistry(): Promise<FleetLoop[]> {
  const registryPath = path.join(jarvisHome(), ".claude", "loops", "registry.json");
  const raw = await fs.readFile(registryPath, "utf-8");
  const parsed = JSON.parse(raw) as { loops?: RegistryLoop[] };
  const now = Date.now();

  return (parsed.loops ?? []).map((loop) => {
    const { ts, color } = parseHeartbeat(loop.last_heartbeat);
    const cadence = cadenceHours(loop.schedule);
    // stale = heartbeat older than 2x cadence. Loops without a cadence
    // (in-session / registered-only) are never marked stale — they have no
    // contract to be fresh against. A cadenced loop with NO heartbeat is stale.
    let stale = false;
    if (cadence != null) {
      if (ts == null) stale = true;
      else stale = now - ts > 2 * cadence * 3_600_000;
    }
    return {
      id: loop.id,
      status: loop.status ?? "unknown",
      runner: loop.runner ?? "",
      schedule: loop.schedule ?? "",
      last_heartbeat: loop.last_heartbeat ?? null,
      color,
      stale,
    };
  });
}

async function readCanary(): Promise<CanaryReport> {
  const reportPath = path.join(
    jarvisHome(),
    ".claude",
    "loops",
    "env-canary",
    "report-latest.md"
  );
  const raw = await fs.readFile(reportPath, "utf-8");

  const overallMatch = raw.match(/^Overall:\s*(GREEN|RED)\s*$/im);
  const overall: CanaryReport["overall"] =
    overallMatch?.[1]?.toUpperCase() === "GREEN"
      ? "GREEN"
      : overallMatch?.[1]?.toUpperCase() === "RED"
        ? "RED"
        : "UNKNOWN";

  // Header line: "# env-canary run 2026-07-07T01:35:32Z"
  const genMatch = raw.match(/^#\s*env-canary run\s+(\S+)/im);

  // Failing checks: "- [FAIL] name: detail"
  const failing: string[] = [];
  for (const m of raw.matchAll(/^-\s*\[FAIL\]\s*([^\n]+)$/gim)) {
    failing.push(m[1].trim());
  }

  return { overall, failing, generated_at: genMatch?.[1] ?? null };
}

export async function GET() {
  const [registryResult, canaryResult] = await Promise.allSettled([readRegistry(), readCanary()]);

  const loops = registryResult.status === "fulfilled" ? registryResult.value : [];
  const canary =
    canaryResult.status === "fulfilled"
      ? canaryResult.value
      : ({ overall: "UNKNOWN", failing: [], generated_at: null } satisfies CanaryReport);

  const red = loops.filter((l) => l.color === "RED" || l.color === "ERROR");
  const staleLoops = loops.filter((l) => l.stale);
  const green = loops.filter((l) => l.color === "GREEN" && !l.stale);

  return NextResponse.json({
    canary,
    counts: {
      total: loops.length,
      green: green.length,
      red: red.length,
      stale: staleLoops.length,
    },
    red_loops: red.map((l) => l.id),
    stale_loops: staleLoops.map((l) => l.id),
    loops,
    errors: {
      registry: registryResult.status === "rejected" ? String(registryResult.reason) : null,
      canary: canaryResult.status === "rejected" ? String(canaryResult.reason) : null,
    },
    jarvis_home: jarvisHome(),
    generated_at: new Date().toISOString(),
  });
}
