import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";
import { summarizeRuntimeSnapshot, type RawRuntimeSnapshot } from "@/lib/runtimeSnapshot";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function snapshotPath(): string {
  const envPath = process.env.JARVIS_RUNTIME_SNAPSHOT_PATH;
  if (envPath && envPath.trim()) return envPath;
  return path.resolve(process.cwd(), "..", "phase0_runtime_truth_snapshot.json");
}

export async function GET() {
  const filePath = snapshotPath();
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw) as RawRuntimeSnapshot;
    return NextResponse.json(summarizeRuntimeSnapshot(parsed));
  } catch (error) {
    const code = (error as NodeJS.ErrnoException)?.code;
    const loadError = code === "ENOENT" ? "missing_snapshot_file" : code ?? "invalid_snapshot_payload";
    return NextResponse.json(summarizeRuntimeSnapshot(null, Date.now(), loadError));
  }
}
