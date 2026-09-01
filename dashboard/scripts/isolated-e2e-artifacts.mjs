import { existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

export const ARTIFACT_MODES = new Set(["always", "on-failure", "never"]);

export function normalizeArtifactMode(value) {
  const mode = value || "on-failure";
  if (!ARTIFACT_MODES.has(mode)) {
    throw new Error(
      `Invalid JARVIS_E2E_ARTIFACT_MODE=${mode}. Expected one of: always, on-failure, never.`
    );
  }
  return mode;
}

export function shouldArchiveArtifacts(mode, exitCode) {
  return mode === "always" || (mode === "on-failure" && exitCode !== 0);
}

export function shouldCleanArtifacts(mode, exitCode) {
  return mode === "never" || (mode === "on-failure" && exitCode === 0);
}

export function resolveRunOutputPath(dashboardRoot, relativePath) {
  const root = resolve(dashboardRoot);
  const target = resolve(root, relativePath);
  const rel = relative(root, target);
  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
    throw new Error(`Refusing to handle artifact outside dashboard root: ${relativePath}`);
  }
  return target;
}

export function archiveRunOutput({ dashboardRoot, archiveRoot, relativePath, stamp }) {
  const source = resolveRunOutputPath(dashboardRoot, relativePath);
  if (!existsSync(source)) return null;

  mkdirSync(archiveRoot, { recursive: true });
  const base = `${relativePath.replace(/[\\/]/g, "_")}-${stamp}`;
  let destination = join(archiveRoot, base);
  let counter = 1;
  while (existsSync(destination)) {
    destination = join(archiveRoot, `${base}-${counter}`);
    counter += 1;
  }
  renameSync(source, destination);
  return destination;
}

export function cleanRunOutput(dashboardRoot, relativePath) {
  const target = resolveRunOutputPath(dashboardRoot, relativePath);
  if (!existsSync(target)) return null;

  rmSync(target, { recursive: true, force: true });
  return target;
}

export function handleRunArtifacts({
  dashboardRoot,
  archiveRoot,
  outputs,
  mode,
  exitCode,
  stamp,
}) {
  const archived = [];
  const cleaned = [];

  if (shouldArchiveArtifacts(mode, exitCode)) {
    for (const relativePath of outputs) {
      const destination = archiveRunOutput({ dashboardRoot, archiveRoot, relativePath, stamp });
      if (destination) archived.push(destination);
    }
    return { archived, cleaned };
  }

  if (shouldCleanArtifacts(mode, exitCode)) {
    for (const relativePath of outputs) {
      const target = cleanRunOutput(dashboardRoot, relativePath);
      if (target) cleaned.push(target);
    }
  }

  return { archived, cleaned };
}
