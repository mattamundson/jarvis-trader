import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const commandCenterPage = join(process.cwd(), "app", "command-center", "page.tsx");
const legacyComponentsDir = join(process.cwd(), "app", "mission-control", "components");

test("command center imports operations panels from neutral component ownership", () => {
  const source = readFileSync(commandCenterPage, "utf8");

  assert.ok(
    !source.includes("@/app/mission-control/components"),
    "command-center page must not import reusable panels from the redirected mission-control route",
  );
  assert.match(
    source,
    /@\/components\/command-center\/operations\/RiskSafetyPanel/,
    "command-center page should import migrated operations panels from the neutral module",
  );
});

test("legacy mission-control route no longer owns reusable panel sources", () => {
  if (!existsSync(legacyComponentsDir)) return;

  const tsxFiles = readdirSync(legacyComponentsDir).filter((name) => name.endsWith(".tsx"));
  assert.deepEqual(tsxFiles, []);
});
