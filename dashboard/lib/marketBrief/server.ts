import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { degradedMarketBrief, extractMachinePayload, summarizeMachinePayload } from "./summary";
import type { MarketBriefSnapshot } from "./types";

const DEFAULT_MARKET_BRIEF_DIR = "C:/Users/mattm/master-jarvis/second-brain/reports/night-shift";
const MACHINE_BRIEF_PREFIX = "MORNING_BRIEF_MACHINE_SCORED_PREVIEW_";

async function latestMarketBriefPath(dir: string): Promise<string | null> {
  const entries = await readdir(dir, { withFileTypes: true });
  const candidates: Array<{ file: string; mtimeMs: number }> = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    if (!entry.name.startsWith(MACHINE_BRIEF_PREFIX) || !entry.name.endsWith(".md")) continue;
    const file = path.join(dir, entry.name);
    const meta = await stat(file);
    candidates.push({ file, mtimeMs: meta.mtimeMs });
  }
  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return candidates[0]?.file ?? null;
}

export async function loadLatestMarketBrief(nowMs = Date.now()): Promise<MarketBriefSnapshot> {
  const dir = process.env.MARKET_BRIEF_DIR || DEFAULT_MARKET_BRIEF_DIR;
  try {
    const file = await latestMarketBriefPath(dir);
    if (!file) return degradedMarketBrief(`No ${MACHINE_BRIEF_PREFIX}*.md artifact found in ${dir}.`);
    const [markdown, meta] = await Promise.all([readFile(file, "utf8"), stat(file)]);
    const payload = extractMachinePayload(markdown);
    return summarizeMachinePayload(payload, { sourcePath: file, sourceMtimeMs: meta.mtimeMs, nowMs });
  } catch (error) {
    return degradedMarketBrief(error instanceof Error ? error.message : "Unknown market brief load error");
  }
}

export * from "./types";
export * from "./summary";
