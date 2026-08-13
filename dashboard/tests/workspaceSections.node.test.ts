import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveWorkspaceSection } from "../lib/workspaceSections.ts";
import { VALIDATION_SECTIONS } from "../components/validation/validationSections.ts";
import { PERFORMANCE_SECTIONS } from "../components/performance/performanceSections.ts";

test("validation defaults to summary and exposes all required drill-down sections", () => {
  assert.equal(resolveWorkspaceSection(VALIDATION_SECTIONS, null), "summary");
  assert.deepEqual(VALIDATION_SECTIONS.map((s) => s.id), [
    "summary", "paper", "backtest", "wfe", "reconciliation", "audit",
  ]);
});

test("validation resolves an unrecognized section id back to summary", () => {
  assert.equal(resolveWorkspaceSection(VALIDATION_SECTIONS, "not-a-real-section"), "summary");
  assert.equal(resolveWorkspaceSection(VALIDATION_SECTIONS, undefined), "summary");
});

test("validation resolves a known section id to itself", () => {
  for (const id of ["paper", "backtest", "wfe", "reconciliation", "audit"]) {
    assert.equal(resolveWorkspaceSection(VALIDATION_SECTIONS, id), id);
  }
});

test("every validation section has a stable id, label, summary, and lazy component loader", () => {
  const seen = new Set<string>();
  for (const section of VALIDATION_SECTIONS) {
    assert.equal(typeof section.id, "string");
    assert.ok(section.id.length > 0, "id must be non-empty");
    assert.ok(!seen.has(section.id), `duplicate section id: ${section.id}`);
    seen.add(section.id);
    assert.equal(typeof section.label, "string");
    assert.ok(section.label.length > 0, "label must be non-empty");
    assert.equal(typeof section.summary, "string");
    assert.ok(section.summary.length > 0, "summary must be non-empty");
    assert.equal(typeof section.loadComponent, "function");
  }
});

test("performance defaults to summary and exposes all required drill-down sections", () => {
  assert.equal(resolveWorkspaceSection(PERFORMANCE_SECTIONS, null), "summary");
  assert.deepEqual(PERFORMANCE_SECTIONS.map((s) => s.id), [
    "summary", "risk", "time", "execution", "research",
  ]);
});

test("performance resolves an unrecognized section id back to summary", () => {
  assert.equal(resolveWorkspaceSection(PERFORMANCE_SECTIONS, "bogus"), "summary");
  assert.equal(resolveWorkspaceSection(PERFORMANCE_SECTIONS, null), "summary");
});

test("every performance section has a stable id, label, summary, and lazy component loader", () => {
  const seen = new Set<string>();
  for (const section of PERFORMANCE_SECTIONS) {
    assert.equal(typeof section.id, "string");
    assert.ok(section.id.length > 0, "id must be non-empty");
    assert.ok(!seen.has(section.id), `duplicate section id: ${section.id}`);
    seen.add(section.id);
    assert.equal(typeof section.label, "string");
    assert.ok(section.label.length > 0, "label must be non-empty");
    assert.equal(typeof section.summary, "string");
    assert.ok(section.summary.length > 0, "summary must be non-empty");
    assert.equal(typeof section.loadComponent, "function");
  }
});
