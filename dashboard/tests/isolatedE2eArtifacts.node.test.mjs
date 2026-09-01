import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import {
  archiveRunOutput,
  cleanRunOutput,
  normalizeArtifactMode,
  resolveRunOutputPath,
  shouldArchiveArtifacts,
  shouldCleanArtifacts,
} from "../scripts/isolated-e2e-artifacts.mjs";

function withTempRoot(fn) {
  const root = mkdtempSync(join(tmpdir(), "jarvis-isolated-artifacts-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("artifact mode defaults to on-failure and validates known modes", () => {
  assert.equal(normalizeArtifactMode(undefined), "on-failure");
  assert.equal(normalizeArtifactMode("always"), "always");
  assert.equal(normalizeArtifactMode("on-failure"), "on-failure");
  assert.equal(normalizeArtifactMode("never"), "never");
  assert.throws(() => normalizeArtifactMode("sometimes"), /Invalid JARVIS_E2E_ARTIFACT_MODE/);
});

test("artifact mode decisions preserve failed evidence and clean successful temp outputs", () => {
  assert.equal(shouldArchiveArtifacts("on-failure", 1), true);
  assert.equal(shouldArchiveArtifacts("on-failure", 0), false);
  assert.equal(shouldArchiveArtifacts("always", 0), true);
  assert.equal(shouldArchiveArtifacts("never", 1), false);

  assert.equal(shouldCleanArtifacts("on-failure", 0), true);
  assert.equal(shouldCleanArtifacts("on-failure", 1), false);
  assert.equal(shouldCleanArtifacts("never", 1), true);
  assert.equal(shouldCleanArtifacts("always", 0), false);
});

test("run output path handling is restricted to dashboard root children", () =>
  withTempRoot((root) => {
    assert.equal(resolveRunOutputPath(root, ".next-codex-isolated"), resolve(root, ".next-codex-isolated"));
    assert.throws(() => resolveRunOutputPath(root, "."), /outside dashboard root/);
    assert.throws(() => resolveRunOutputPath(root, ".."), /outside dashboard root/);
    assert.throws(() => resolveRunOutputPath(root, resolve(root, "..", "outside")), /outside dashboard root/);
  }));

test("successful-run cleanup removes only current temp output paths", () =>
  withTempRoot((root) => {
    const output = join(root, ".next-codex-isolated");
    mkdirSync(output);
    writeFileSync(join(output, "BUILD_ID"), "test");

    const removed = cleanRunOutput(root, ".next-codex-isolated");
    assert.equal(removed, output);
    assert.equal(existsSync(output), false);
  }));

test("failed-run archive moves current output paths into stamped archive root", () =>
  withTempRoot((root) => {
    const archiveRoot = join(root, "archive");
    const output = join(root, "test-results");
    mkdirSync(output);
    writeFileSync(join(output, "result.txt"), "failed");

    const archived = archiveRunOutput({
      dashboardRoot: root,
      archiveRoot,
      relativePath: "test-results",
      stamp: "20260901-000000",
    });

    assert.equal(archived, join(archiveRoot, "test-results-20260901-000000"));
    assert.equal(existsSync(output), false);
    assert.equal(existsSync(join(archived, "result.txt")), true);
  }));
