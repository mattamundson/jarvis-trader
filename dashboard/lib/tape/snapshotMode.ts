// Item 8: snapshot mode. On Vercel (or TAPE_SNAPSHOT_MODE=1) /tape and its
// extras read published JSON snapshots instead of the local PC/engine.
// Snapshots live in data/tape-snapshots/ and are bundled at build time; the
// publisher (scripts/publish-tape-snapshot.mjs) commits fresh ones and pushes.
import flowTape from "@/data/tape-snapshots/flow-tape.json";
import tapeExtras from "@/data/tape-snapshots/tape-extras.json";

export function isSnapshotMode(): boolean {
  if (process.env.TAPE_SNAPSHOT_MODE === "1") return true;
  if (process.env.TAPE_SNAPSHOT_MODE === "0") return false;
  return process.env.VERCEL === "1";
}

/** Read-only deploy: engine/broker proxies accept GET/HEAD/OPTIONS only. */
export function isReadOnlyDeploy(): boolean {
  if (process.env.READ_ONLY_DEPLOY === "0") return false;
  return process.env.READ_ONLY_DEPLOY === "1" || process.env.VERCEL === "1";
}

function ageS(publishedAt: unknown): number | null {
  const t = typeof publishedAt === "number" ? publishedAt : Date.parse(String(publishedAt ?? ""));
  return Number.isFinite(t) ? Math.round((Date.now() - t) / 1000) : null;
}

export function flowTapeSnapshot() {
  const s: any = flowTape;
  return { ...s, snapshotMode: true, snapshotAgeS: ageS(s.publishedAt), stale10m: (ageS(s.publishedAt) ?? 1e9) > 600 };
}

export function tapeExtrasSnapshot() {
  const s: any = tapeExtras;
  return { ...s, snapshotMode: true, snapshotAgeS: ageS(s.publishedAt) };
}
