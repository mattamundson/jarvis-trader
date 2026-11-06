import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, writeFile } from "node:fs/promises";
import { parseHermesGates, readHermesGates } from "../lib/hermesGates.ts";
import { bookDisagreements } from "../lib/bookDisagreement.ts";

test("parses status lines and ignores prose", () => {
  const parsed = parseHermesGates(`
# Hermes
Paper trading stays on.

- MES paper path: pass
- IB connected: pass
Random sentence with a colon: not a status word
lockout: off
`);
  assert.deepEqual(parsed.gates, [
    { name: "MES paper path", status: "pass" },
    { name: "IB connected", status: "pass" },
  ]);
  assert.equal(parsed.fileLockout, false);
});

test("missing gates file returns not found", async () => {
  const report = await readHermesGates({
    TAPE_STATE_DIR: path.join(os.tmpdir(), "does-not-exist"),
    USERPROFILE: path.join(os.tmpdir(), "no-such-home"),
    HOME: path.join(os.tmpdir(), "no-such-home"),
  } as NodeJS.ProcessEnv);
  assert.equal(report.found, false);
  assert.deepEqual(report.gates, []);
});

test("a gates.md file in .jarvis is read", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "hermes-gates-"));
  const jarvisDir = path.join(dir, ".jarvis");
  const { mkdir } = await import("node:fs/promises");
  await mkdir(jarvisDir, { recursive: true });
  const file = path.join(jarvisDir, "gates.md");
  await writeFile(file, "- Engine health: pass\nlockout: on\n", "utf8");
  const found = await readHermesGates({
    HOME: dir,
  } as NodeJS.ProcessEnv);
  assert.equal(found.found, true);
  assert.equal(found.gates[0]?.name, "Engine health");
  assert.equal(found.fileLockout, true);
});

test("book disagreement names symbol and quantity only", () => {
  assert.deepEqual(
    bookDisagreements(
      [{ symbol: "MES", quantity: 1 }],
      [],
    ),
    ["MES quantity 1 on /portfolio and 0 on /portfolio/paper/positions"],
  );
  assert.deepEqual(
    bookDisagreements([{ symbol: "mes", quantity: 1 }], [{ symbol: "MES", quantity: 1 }]),
    [],
  );
});
