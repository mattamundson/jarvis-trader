import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, writeFile } from "node:fs/promises";
import { hermesGatesCandidates, parseHermesGates, readHermesGates } from "../lib/hermesGates.ts";

const BRIDGE_MD = `# Hermes gates (sanitised bridge; names and status only)
- Premarket readiness 12 of 15 (2026-10-20, 6d old): warn
- IB gateway alive (last report): warn
- Broker id matches gateway (last report): warn
- Paper mode, approved record (approved 2026-09-18): pass
- Live trading OFF, approved record (approved 2026-09-18): pass
- Kill switch clear, approved record (approved 2026-09-18): pass
`;

test("tape state dir gates.md is a candidate and the bridge format parses", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "tape-state-"));
  await writeFile(path.join(dir, "gates.md"), BRIDGE_MD, "utf8");
  const env = { TAPE_STATE_DIR: dir, USERPROFILE: path.join(os.tmpdir(), "no-such-home"), HOME: path.join(os.tmpdir(), "no-such-home") } as NodeJS.ProcessEnv;
  assert.ok(hermesGatesCandidates(env).includes(path.join(dir, "gates.md")));
  const report = await readHermesGates(env);
  assert.equal(report.found, true);
  assert.equal(report.gates.length, 6);
  assert.deepEqual(report.gates.slice(0, 3).map((g) => g.status), ["warn", "warn", "warn"]);
  assert.equal(report.gates[5].status, "pass");
  assert.equal(report.fileLockout, null);
});

test("a fresh-report bridge file carries the lockout line", () => {
  const p = parseHermesGates("- Premarket readiness 15 of 15 (today): pass\nlockout: off\n");
  assert.equal(p.gates[0].status, "pass");
  assert.equal(p.fileLockout, false);
});
