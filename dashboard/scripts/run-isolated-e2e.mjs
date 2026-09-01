#!/usr/bin/env node
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { handleRunArtifacts, normalizeArtifactMode } from "./isolated-e2e-artifacts.mjs";

const DASHBOARD_ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const NEXT_ENV_PATH = join(DASHBOARD_ROOT, "next-env.d.ts");
const TSCONFIG_PATH = join(DASHBOARD_ROOT, "tsconfig.json");
const DIST_DIR = process.env.NEXT_DIST_DIR || ".next-codex-isolated";
const ARCHIVE_ROOT = join(
  homedir(),
  "Archive",
  String(new Date().getFullYear()),
  "jarvis-temp-build-artifacts",
);

function stamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+$/, "").replace("T", "-");
}

function readSnapshot(path) {
  return existsSync(path) ? readFileSync(path) : null;
}

function restoreSnapshot(path, snapshot) {
  if (snapshot == null) return;
  writeFileSync(path, snapshot);
}

function run(command, args, env) {
  console.log(`\n> ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, {
    cwd: DASHBOARD_ROOT,
    env,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  return typeof result.status === "number" ? result.status : 1;
}

const nextEnvSnapshot = readSnapshot(NEXT_ENV_PATH);
const tsconfigSnapshot = readSnapshot(TSCONFIG_PATH);
const playwrightArgs = process.argv.slice(2);
const artifactMode = normalizeArtifactMode(process.env.JARVIS_E2E_ARTIFACT_MODE);
const env = {
  ...process.env,
  NEXT_DIST_DIR: DIST_DIR,
  DASHBOARD_AUTH_USER: process.env.DASHBOARD_AUTH_USER ?? "",
  DASHBOARD_AUTH_PASS: process.env.DASHBOARD_AUTH_PASS ?? "",
};

let exitCode = 0;
try {
  exitCode = run("pnpm", ["run", "build"], env);
  if (exitCode === 0) {
    exitCode = run("pnpm", ["exec", "playwright", "test", "-c", "playwright.fresh.config.ts", ...playwrightArgs], env);
  }
} finally {
  restoreSnapshot(NEXT_ENV_PATH, nextEnvSnapshot);
  restoreSnapshot(TSCONFIG_PATH, tsconfigSnapshot);

  const { archived, cleaned } = handleRunArtifacts({
    dashboardRoot: DASHBOARD_ROOT,
    archiveRoot: ARCHIVE_ROOT,
    outputs: [DIST_DIR, "test-results"],
    mode: artifactMode,
    exitCode,
    stamp: stamp(),
  });

  for (const destination of archived) {
    console.log(`archived ${destination}`);
  }
  for (const target of cleaned) {
    console.log(`removed temp artifact ${target}`);
  }
}

process.exit(exitCode);
