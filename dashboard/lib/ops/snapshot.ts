import { maskDeep } from "@/lib/ops/mask";
import {
  parseJournal, parseLadder, parseLockout, parseScoredCsv, parseStrikeLog,
  type Journal, type LadderBundle, type Lockout, type ScoredCsv, type StrikeLog,
} from "@/lib/ops/parse";

/** The closed list of Hermes files this view may read. Nothing request-controlled ever picks a path. */
export const OPS_FILES = {
  tracker: "rebuild-ladder-tracker.md",
  strikeLog: "strike-log.md",
  lockout: "lockout-release-checklist.md",
  journal: "paper-journal.md",
  scoredCsv: "scored-setups.csv",
} as const;
export type OpsFileKey = keyof typeof OPS_FILES;

export interface FileMeta { key: OpsFileKey; name: string; found: boolean; bytes: number | null; mtimeIso: string | null; ageHours: number | null; stale: boolean }

export interface OpsSnapshot {
  generatedIso: string;
  dir: string | null;
  files: FileMeta[];
  ladder: LadderBundle | null;
  strikes: StrikeLog | null;
  lockout: Lockout | null;
  journal: Journal | null;
  scoredCsv: ScoredCsv | null;
  /** Honest cross-checks and gaps: shown on the page, never hidden. */
  warnings: string[];
  /** Fixed stance for this view. The record decides nothing here; this page never grants anything. */
  liveLegal: "NO";
  size: 0;
}

export const STALE_HOURS = 36;

export type OpsTexts = Partial<Record<OpsFileKey, string>>;
export type OpsMeta = Partial<Record<OpsFileKey, { bytes: number; mtimeMs: number }>>;

/** Build the snapshot from file texts. Pure: every string in the result is masked here, once. */
export function buildOpsSnapshot(texts: OpsTexts, meta: OpsMeta, now: Date, dir: string | null): OpsSnapshot {
  const warnings: string[] = [];
  const files: FileMeta[] = (Object.keys(OPS_FILES) as OpsFileKey[]).map((key) => {
    const m = meta[key];
    const ageHours = m ? (now.getTime() - m.mtimeMs) / 3_600_000 : null;
    return {
      key, name: OPS_FILES[key], found: texts[key] !== undefined, bytes: m?.bytes ?? null,
      mtimeIso: m ? new Date(m.mtimeMs).toISOString() : null,
      ageHours: ageHours === null ? null : Math.round(ageHours * 10) / 10,
      stale: ageHours === null ? false : ageHours > STALE_HOURS,
    };
  });

  const ladder = texts.tracker !== undefined ? parseLadder(texts.tracker) : null;
  const strikes = texts.strikeLog !== undefined ? parseStrikeLog(texts.strikeLog) : null;
  const lockout = parseLockout(strikes, texts.lockout ?? null, ladder?.ladder ?? null, now);
  const journal = texts.journal !== undefined ? parseJournal(texts.journal) : null;
  const scoredCsv = texts.scoredCsv !== undefined ? parseScoredCsv(texts.scoredCsv) : null;

  for (const f of files) if (!f.found) warnings.push(`${f.name} not found in the Hermes directory.`);
  for (const f of files) if (f.found && f.stale) warnings.push(`${f.name} is ${Math.round(f.ageHours ?? 0)}h old (stale after ${STALE_HOURS}h).`);
  if (ladder && ladder.ladder.scored === null) warnings.push("Scored setups / avg R not found in the tracker's Current state table.");
  if (ladder?.ladder.scored && scoredCsv && scoredCsv.rows !== ladder.ladder.scored.n) {
    warnings.push(`Tracker says ${ladder.ladder.scored.n} scored setups; scored-setups.csv has ${scoredCsv.rows} rows. The tracker is the record; the csv has not caught up.`);
  }
  if (ladder?.ladder.strikes30d != null && strikes?.confirmedCount != null && ladder.ladder.strikes30d !== strikes.confirmedCount) {
    warnings.push(`Tracker counts ${ladder.ladder.strikes30d} strikes; strike-log.md counts ${strikes.confirmedCount}.`);
  }
  if (strikes && strikes.pending.length) warnings.push(`${strikes.pending.length} strike(s) pending Matt's confirmation; they are not in the confirmed count.`);

  return maskDeep({
    generatedIso: now.toISOString(), dir, files, ladder, strikes, lockout, journal, scoredCsv, warnings,
    liveLegal: "NO" as const, size: 0 as const,
  });
}
