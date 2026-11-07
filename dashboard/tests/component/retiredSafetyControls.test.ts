// The executable safety UI controls CircuitBreakerPanel and KillSwitch were
// deliberately removed in 7ff10747 (Aug 2026). Other inline operator controls
// still exist on master; these tests do NOT certify their behavior or authority.
// This only guards the two retired standalone modules. The original component
// suites that exercised the removed controls are archived (moved, not
// deleted) at docs/archives/retired-component-tests/ — see
// KillSwitch.test.tsx.txt and CircuitBreakerPanel.test.tsx.txt for the
// historical tripped/untripped and failed-POST-never-flips-state coverage.
//
// This suite pins the current contract:
//   1. the removed component modules are NOT reintroduced anywhere in
//      dashboard source via the checked standalone paths — a re-added module must fail CI and get
//      explicit review, never slip back in silently;
//   2. the existing API helper exports remain present. Export presence is
//      NOT a behavioral safety certification and invokes no endpoint.
// No engine calls are made: lib/api is imported, never invoked.
import { describe, expect, it } from "vitest";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DASHBOARD_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  ".."
);

const SOURCE_DIRS = ["app", "components", "lib", "hooks"];
const REMOVED_CONTROLS = ["CircuitBreakerPanel", "KillSwitch"];
const REMOVED_IMPORT_RE =
  /from\s+["']@\/components\/(CircuitBreakerPanel|KillSwitch)["']/;

function listSourceFiles(dir: string, acc: string[] = []): string[] {
  if (!existsSync(dir)) {
    return acc;
  }
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      listSourceFiles(full, acc);
    } else if (/\.(ts|tsx|js|jsx)$/.test(name)) {
      acc.push(full);
    }
  }
  return acc;
}

describe("retired safety controls stay retired (removed in 7ff10747)", () => {
  it.each(REMOVED_CONTROLS)(
    "no %s component module exists under components/",
    (name) => {
      const present = ["tsx", "ts", "jsx", "js"].some((ext) =>
        existsSync(path.join(DASHBOARD_ROOT, "components", `${name}.${ext}`))
      );
      expect(present).toBe(false);
    }
  );

  it("no dashboard source file imports the removed control components", () => {
    const offenders = SOURCE_DIRS.flatMap((dir) =>
        listSourceFiles(path.join(DASHBOARD_ROOT, dir))
      )
      .map((file) => ({ file, text: readFileSync(file, "utf8") }))
      .filter(({ text }) => REMOVED_IMPORT_RE.test(text))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it("existing kill-switch API helper exports remain present (import-only contract)", async () => {
    const api = (await import("@/lib/api")) as unknown as Record<
      string,
      unknown
    >;
    expect(typeof api.fetchKillSwitchStatus).toBe("function");
    expect(typeof api.toggleKillSwitch).toBe("function");
  });
});
