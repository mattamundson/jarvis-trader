import { test } from "node:test";
import assert from "node:assert/strict";
import {
  RESEARCH_INTAKE_ROWS,
  commandCenterResearchIntakeRows,
  summarizeResearchIntake,
} from "../lib/researchIntake.ts";

test("research intake rows are normalized and non-authorizing", () => {
  assert.equal(RESEARCH_INTAKE_ROWS.length, 9);
  for (const row of RESEARCH_INTAKE_ROWS) {
    assert.match(row.id, /^(pr|issue)-\d+$/);
    assert.equal(row.readiness_impact, "none");
    assert.ok(row.evidence.includes("docs/plans/master-implementation/PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md"));
    assert.notEqual(row.disposition, "replace");
  }
});

test("research intake summary tracks disposition counts", () => {
  const summary = summarizeResearchIntake();
  assert.equal(summary.total, 9);
  assert.equal(summary.byDisposition.keep, 6);
  assert.equal(summary.byDisposition.reference, 2);
  assert.equal(summary.byDisposition.defer, 1);
  assert.equal(summary.readinessImpactRows, 0);
});

test("command center gets the highest-signal intake rows first", () => {
  const rows = commandCenterResearchIntakeRows();
  assert.deepEqual(rows.map((row) => row.id), ["pr-749", "pr-754", "pr-756", "pr-755"]);
});
