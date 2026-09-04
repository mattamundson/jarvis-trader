import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { inspectSourceIntegrity, summarizeSourceIntegrity } from "../lib/sourceIntegrity.ts";

async function materializeValidRepo(root: string) {
  const dirs = [
    "engine",
    "dashboard",
    "docs",
    "engine/tests",
    ".github/workflows",
    "engine/risk",
    "engine/agents",
    "engine/execution",
    "engine/approval",
    "engine/portfolio",
    "dashboard/app",
    "dashboard/lib",
    ".git/objects",
    ".git/refs",
    ".github/actions/free-disk-space",
  ];
  for (const rel of dirs) {
    await mkdir(path.join(root, rel), { recursive: true });
  }

  const files = [
    "AGENTS.md",
    "CLAUDE.md",
    "engine/CLAUDE.md",
    "engine/main.py",
    "engine/config.py",
    "engine/requirements-core.txt",
    "engine/risk/safety_layer.py",
    "engine/agents/pipeline.py",
    "engine/execution/ib_gateway.py",
    "engine/approval/service.py",
    "engine/portfolio/tracker.py",
    "dashboard/AGENTS.md",
    "dashboard/CLAUDE.md",
    "dashboard/package.json",
    ".git/HEAD",
    ".git/config",
    ".github/workflows/ci.yml",
    ".github/actions/free-disk-space/action.yml",
  ];

  for (const rel of files) {
    await mkdir(path.dirname(path.join(root, rel)), { recursive: true });
    let content = "# fixture\n";
    if (rel === ".git/HEAD") content = "ref: refs/heads/master\n";
    if (rel === ".git/config") content = "[core]\nrepositoryformatversion = 0\n";
    if (rel === ".github/workflows/ci.yml") content = "name: ci\njobs:\n  check:\n    steps:\n      - uses: ./.github/actions/free-disk-space\n";
    if (rel === ".github/actions/free-disk-space/action.yml") content = "name: free disk space\nruns:\n  using: composite\n";
    await writeFile(path.join(root, rel), content, "utf-8");
  }
}

test("inspectSourceIntegrity: valid synthetic repo passes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "jarvis-source-integrity-pass-"));
  try {
    await materializeValidRepo(root);
    const out = await inspectSourceIntegrity("fixture", root);
    assert.equal(out.status, "pass");
    assert.equal(out.finding_count, 0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("inspectSourceIntegrity: config-only .git fails metadata checks", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "jarvis-source-integrity-fail-"));
  try {
    await materializeValidRepo(root);
    await rm(path.join(root, ".git", "HEAD"), { force: true });
    await rm(path.join(root, ".git", "objects"), { recursive: true, force: true });
    await rm(path.join(root, ".git", "refs"), { recursive: true, force: true });
    const out = await inspectSourceIntegrity("fixture", root);
    assert.equal(out.status, "fail");
    assert.ok(out.git_metadata_failures >= 3);
    assert.match(out.findings.join("\n"), /git_metadata/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("summarizeSourceIntegrity: overall fails when any check fails", () => {
  const summary = summarizeSourceIntegrity([
    {
      label: "active",
      repo_root: "C:/ok",
      status: "pass",
      finding_count: 0,
      required_path_failures: 0,
      git_metadata_failures: 0,
      workflow_action_failures: 0,
      findings: [],
    },
    {
      label: "deploy",
      repo_root: "C:/bad",
      status: "fail",
      finding_count: 2,
      required_path_failures: 1,
      git_metadata_failures: 1,
      workflow_action_failures: 0,
      findings: ["required_path: AGENTS.md missing", "git_metadata: .git missing or unreadable"],
    },
  ]);

  assert.equal(summary.overall, "fail");
  assert.deepEqual(summary.failing_labels, ["deploy"]);
  assert.equal(summary.pass_count, 1);
  assert.equal(summary.fail_count, 1);
});
