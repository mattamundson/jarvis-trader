import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";
import { summarizeRuntimeSnapshot, type RawRuntimeSnapshot } from "@/lib/runtimeSnapshot";
import { inspectSourceIntegrity, summarizeSourceIntegrity } from "@/lib/sourceIntegrity";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function currentRepoRoot(): string {
  return path.resolve(process.cwd(), "..");
}

function snapshotPath(): string {
  const envPath = process.env.JARVIS_RUNTIME_SNAPSHOT_PATH;
  if (envPath && envPath.trim()) return envPath;
  return path.resolve(currentRepoRoot(), "phase0_runtime_truth_snapshot.json");
}

function canonicalDeployRoot(): string {
  const envPath = process.env.JARVIS_DEPLOY_REPO_PATH;
  if (envPath && envPath.trim()) return path.resolve(envPath);
  return currentRepoRoot();
}

function referenceRepoRoot(): string | null {
  const envPath = process.env.JARVIS_REFERENCE_REPO_PATH;
  if (envPath && envPath.trim()) return path.resolve(envPath);
  return null;
}

async function loadSourceIntegrity() {
  const checks: Array<{ label: string; repoRoot: string }> = [];
  const seen = new Set<string>();
  const pushTarget = (label: string, repoRoot: string | null) => {
    if (!repoRoot) return;
    const resolved = path.resolve(repoRoot);
    const key = `${label}::${resolved}`;
    if (seen.has(key)) return;
    seen.add(key);
    checks.push({ label, repoRoot: resolved });
  };

  pushTarget("Active checkout", currentRepoRoot());
  pushTarget("Canonical deploy", canonicalDeployRoot());
  pushTarget("Reference checkout", referenceRepoRoot());

  const results = await Promise.all(
    checks.map((check) => inspectSourceIntegrity(check.label, check.repoRoot))
  );
  return summarizeSourceIntegrity(results);
}

export async function GET() {
  const filePath = snapshotPath();
  const sourceIntegrity = await loadSourceIntegrity();
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw) as RawRuntimeSnapshot;
    return NextResponse.json({
      ...summarizeRuntimeSnapshot(parsed),
      source_integrity: sourceIntegrity,
    });
  } catch (error) {
    const code = (error as NodeJS.ErrnoException)?.code;
    const loadError = code === "ENOENT" ? "missing_snapshot_file" : code ?? "invalid_snapshot_payload";
    return NextResponse.json({
      ...summarizeRuntimeSnapshot(null, Date.now(), loadError),
      source_integrity: sourceIntegrity,
    });
  }
}
