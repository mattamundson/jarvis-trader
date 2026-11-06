import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface ProofSetup {
  date: string;
  setup: string;
  side: string;
  trigger: string;
  entry_time: string;
  entry: number;
  stop: number;
  target: number;
  exit_time: string;
  exit: number;
  exit_reason: string;
  R: number;
  rule_breaks?: string[];
  status: string;
  counted: boolean;
}

interface ProofRecordFile {
  generated_ct: string;
  goal_setups: number;
  counted: number;
  avg_R: number;
  total_R: number;
  wins: number;
  losses: number;
  r_basis: string;
  strikes?: number;
  setups: ProofSetup[];
}

interface ProofRecordResponse {
  available: boolean;
  source?: string;
  error?: string;
  goal_setups: number;
  counted: number;
  avg_r: number | null;
  total_r: number | null;
  wins: number;
  losses: number;
  generated_ct?: string;
  setups: ProofSetup[];
}

function normalizeSetup(s: ProofSetup): ProofSetup {
  return {
    ...s,
    R: typeof (s as any).r_multiple === "number" ? (s as any).r_multiple : s.R,
  };
}

function recomputeStats(setups: ProofSetup[]): {
  counted: number;
  wins: number;
  losses: number;
  avg_r: number | null;
  total_r: number;
} {
  const countedSetups = setups.filter((s) => s.counted);
  const total_r = countedSetups.reduce((sum, s) => sum + s.R, 0);
  const wins = countedSetups.filter((s) => s.R > 0).length;
  const losses = countedSetups.filter((s) => s.R < 0).length;
  const avg_r = countedSetups.length > 0 ? total_r / countedSetups.length : null;

  return {
    counted: countedSetups.length,
    wins,
    losses,
    avg_r,
    total_r,
  };
}

async function readProofRecordFile(): Promise<ProofRecordResponse | null> {
  const envPath = process.env.JARVIS_PROOF_RECORD_PATH || process.env.PROOF_RECORD_PATH;
  if (!envPath) return null;

  try {
    const raw = await fs.readFile(envPath, "utf-8");
    const parsed = JSON.parse(raw) as ProofRecordFile;
    const normalized = parsed.setups.map(normalizeSetup);
    const stats = recomputeStats(normalized);

    return {
      available: true,
      source: "file",
      goal_setups: parsed.goal_setups || 20,
      counted: stats.counted,
      avg_r: stats.avg_r,
      total_r: stats.total_r,
      wins: stats.wins,
      losses: stats.losses,
      generated_ct: parsed.generated_ct,
      setups: normalized,
    };
  } catch (error) {
    return null;
  }
}

export async function GET() {
  const fileData = await readProofRecordFile();
  if (fileData) {
    return NextResponse.json(fileData);
  }

  return NextResponse.json({
    available: false,
    error: "Proof record file not found or not configured",
    goal_setups: 20,
    counted: 0,
    avg_r: null,
    total_r: null,
    wins: 0,
    losses: 0,
    setups: [],
  });
}
