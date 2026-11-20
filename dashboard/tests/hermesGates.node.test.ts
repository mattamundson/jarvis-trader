import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, writeFile } from "node:fs/promises";
import { parseHermesGates, readHermesGates } from "../lib/hermesGates.ts";
import { bookDisagreements } from "../lib/bookDisagreement.ts";

test("parses checkbox and status lines and ignores prose", () => {
  const parsed = parseHermesGates(`
# Hermes
Paper trading stays on.

- [x] MES paper path
- [ ] Public engine tunnel
IB connected: pass
Random sentence with a colon: not a status word
lockout: off
`);
  assert.deepEqual(parsed.gates, [
    { name: "MES paper path", status: "pass" },
    { name: "Public engine tunnel", status: "fail" },
    { name: "IB connected", status: "pass" },
  ]);
  assert.equal(parsed.fileLockout, false);
});

test("missing gates file reports the closed message", async () => {
  const report = await readHermesGates({
    HERMES_GATES_PATH: path.join(os.tmpdir(), "does-not-exist-gates.md"),
    USERPROFILE: path.join(os.tmpdir(), "no-such-home"),
    HOME: path.join(os.tmpdir(), "no-such-home"),
  } as NodeJS.ProcessEnv);
  assert.equal(report.found, false);
  assert.equal(report.message, "gates file missing");
  assert.deepEqual(report.gates, []);
});

test("a configured gates.md is read and a non-gates name is ignored", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "hermes-gates-"));
  const file = path.join(dir, "gates.md");
  await writeFile(file, "- [x] Engine health\nlockout: on\n", "utf8");
  const found = await readHermesGates({
    HERMES_GATES_PATH: file,
    USERPROFILE: dir,
    HOME: dir,
  } as NodeJS.ProcessEnv);
  assert.equal(found.found, true);
  assert.equal(found.gates[0]?.name, "Engine health");
  assert.equal(found.fileLockout, true);

  const rejected = await readHermesGates({
    HERMES_GATES_PATH: path.join(dir, ".env"),
    USERPROFILE: dir,
    HOME: dir,
  } as NodeJS.ProcessEnv);
  assert.equal(rejected.found, false);
  assert.equal(rejected.message, "gates file missing");
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
