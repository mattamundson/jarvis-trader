import { promises as fs } from "node:fs";
import path from "node:path";

export type SourceIntegrityStatus = "pass" | "fail" | "unknown";

export interface SourceIntegrityCheck {
  label: string;
  repo_root: string;
  status: SourceIntegrityStatus;
  finding_count: number;
  required_path_failures: number;
  git_metadata_failures: number;
  workflow_action_failures: number;
  findings: string[];
}

export interface SourceIntegritySummary {
  overall: SourceIntegrityStatus;
  checks: SourceIntegrityCheck[];
  pass_count: number;
  fail_count: number;
  unknown_count: number;
  failing_labels: string[];
}

const REQUIRED_PATHS: Array<{ kind: "dir" | "file"; relPath: string }> = [
  { kind: "dir", relPath: "engine" },
  { kind: "dir", relPath: "dashboard" },
  { kind: "dir", relPath: "docs" },
  { kind: "dir", relPath: "engine/tests" },
  { kind: "dir", relPath: ".github/workflows" },
  { kind: "file", relPath: "AGENTS.md" },
  { kind: "file", relPath: "CLAUDE.md" },
  { kind: "file", relPath: "engine/CLAUDE.md" },
  { kind: "file", relPath: "engine/main.py" },
  { kind: "file", relPath: "engine/config.py" },
  { kind: "file", relPath: "engine/requirements-core.txt" },
  { kind: "file", relPath: "engine/risk/safety_layer.py" },
  { kind: "file", relPath: "engine/agents/pipeline.py" },
  { kind: "file", relPath: "engine/execution/ib_gateway.py" },
  { kind: "file", relPath: "engine/approval/service.py" },
  { kind: "file", relPath: "engine/portfolio/tracker.py" },
  { kind: "file", relPath: "dashboard/AGENTS.md" },
  { kind: "file", relPath: "dashboard/CLAUDE.md" },
  { kind: "file", relPath: "dashboard/package.json" },
  { kind: "dir", relPath: "dashboard/app" },
  { kind: "dir", relPath: "dashboard/lib" },
];

const LOCAL_ACTION_RE = /uses:\s*(?:['"])?\.\/(\.github\/actions\/[^\s'"]+)/g;

async function statSafe(target: string) {
  try {
    return await fs.stat(target);
  } catch {
    return null;
  }
}

async function existsDir(target: string): Promise<boolean> {
  const stat = await statSafe(target);
  return !!stat?.isDirectory();
}

async function existsFile(target: string): Promise<boolean> {
  const stat = await statSafe(target);
  return !!stat?.isFile();
}

async function readTextSafe(target: string): Promise<string | null> {
  try {
    return await fs.readFile(target, "utf-8");
  } catch {
    return null;
  }
}

async function resolveWorktreeCommonGitDir(gitDir: string): Promise<string | null> {
  const commondirPath = path.join(gitDir, "commondir");
  const raw = (await readTextSafe(commondirPath))?.trim();
  if (!raw) return null;
  return path.resolve(gitDir, raw);
}

async function resolveGitDir(repoRoot: string): Promise<string | null> {
  const marker = path.join(repoRoot, ".git");
  if (await existsDir(marker)) return marker;
  if (!(await existsFile(marker))) return null;

  const text = (await readTextSafe(marker))?.trim() ?? "";
  if (!text.toLowerCase().startsWith("gitdir:")) return null;
  const raw = text.slice("gitdir:".length).trim();
  if (!raw) return null;
  return path.resolve(repoRoot, raw);
}

export async function inspectSourceIntegrity(label: string, repoRoot: string | null | undefined): Promise<SourceIntegrityCheck> {
  if (!repoRoot || !repoRoot.trim()) {
    return {
      label,
      repo_root: "",
      status: "unknown",
      finding_count: 1,
      required_path_failures: 0,
      git_metadata_failures: 0,
      workflow_action_failures: 0,
      findings: ["repo root was not configured"],
    };
  }

  const resolvedRoot = path.resolve(repoRoot);
  const findings: string[] = [];
  let requiredPathFailures = 0;
  let gitMetadataFailures = 0;
  let workflowActionFailures = 0;

  for (const item of REQUIRED_PATHS) {
    const fullPath = path.join(resolvedRoot, item.relPath);
    const ok = item.kind === "dir" ? await existsDir(fullPath) : await existsFile(fullPath);
    if (!ok) {
      requiredPathFailures += 1;
      findings.push(`required_path: ${item.relPath} missing`);
    }
  }

  const gitDir = await resolveGitDir(resolvedRoot);
  if (!gitDir) {
    gitMetadataFailures += 1;
    findings.push("git_metadata: .git missing or unreadable");
  } else {
    const commonGitDir = (await resolveWorktreeCommonGitDir(gitDir)) ?? gitDir;
    for (const name of ["HEAD", "config", "objects", "refs"]) {
      const baseDir = name === "HEAD" ? gitDir : commonGitDir;
      const fullPath = path.join(baseDir, name);
      const ok = name === "HEAD" || name === "config" ? await existsFile(fullPath) : await existsDir(fullPath);
      if (!ok) {
        gitMetadataFailures += 1;
        findings.push(`git_metadata: ${path.relative(resolvedRoot, fullPath) || name} missing`);
      }
    }
  }

  const workflowsDir = path.join(resolvedRoot, ".github", "workflows");
  if (await existsDir(workflowsDir)) {
    const entries = await fs.readdir(workflowsDir);
    for (const entry of entries.filter((name) => /\.ya?ml$/i.test(name)).sort()) {
      const workflowPath = path.join(workflowsDir, entry);
      const text = (await readTextSafe(workflowPath)) ?? "";
      for (const match of text.matchAll(LOCAL_ACTION_RE)) {
        const actionRel = (match[1] ?? "").replace(/\/+$/, "");
        if (!actionRel) continue;
        const actionYml = path.join(resolvedRoot, actionRel, "action.yml");
        const actionYaml = path.join(resolvedRoot, actionRel, "action.yaml");
        if (!(await existsFile(actionYml)) && !(await existsFile(actionYaml))) {
          workflowActionFailures += 1;
          findings.push(`local_workflow_action: ${path.join(".github", "workflows", entry)} -> ${actionRel} missing`);
        }
      }
    }
  }

  const status: SourceIntegrityStatus = findings.length === 0 ? "pass" : "fail";
  return {
    label,
    repo_root: resolvedRoot,
    status,
    finding_count: findings.length,
    required_path_failures: requiredPathFailures,
    git_metadata_failures: gitMetadataFailures,
    workflow_action_failures: workflowActionFailures,
    findings,
  };
}

export function summarizeSourceIntegrity(checks: SourceIntegrityCheck[]): SourceIntegritySummary {
  const passCount = checks.filter((check) => check.status === "pass").length;
  const failCount = checks.filter((check) => check.status === "fail").length;
  const unknownCount = checks.filter((check) => check.status === "unknown").length;
  return {
    overall: failCount > 0 ? "fail" : passCount > 0 && unknownCount === 0 ? "pass" : "unknown",
    checks,
    pass_count: passCount,
    fail_count: failCount,
    unknown_count: unknownCount,
    failing_labels: checks.filter((check) => check.status === "fail").map((check) => check.label),
  };
}
