// Locks the <Badge> variant vocabulary to exactly seven values.
//
// Why this exists even though BadgeVariant is a TypeScript union (so a bad
// call site like <Badge variant="eighth"> is already a tsc error, and tsc is a
// required check): the union itself can be widened. Adding an eighth member to
// badge.tsx would typecheck perfectly and silently expand the design system's
// color vocabulary, which is what the strict palette is there to prevent.
// The type protects the call sites; this test protects the type.
//
// Reads the source rather than importing it: badge.tsx contains JSX, and the
// node:test runner's --experimental-strip-types does not transform JSX.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BADGE = join(HERE, "..", "components", "ui", "badge.tsx");
const src = readFileSync(BADGE, "utf8");

const EXPECTED = ["bull", "bear", "warn", "info", "neutral", "live", "static"];

function unionMembers(): string[] {
  const m = src.match(/type\s+BadgeVariant\s*=\s*([^;]+);/);
  assert.ok(m, "could not find `type BadgeVariant = ...` in badge.tsx");
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}

function variantMapKeys(): string[] {
  const m = src.match(/const\s+variants\s*:\s*Record<BadgeVariant,\s*string>\s*=\s*\{([\s\S]*?)\n\};/);
  assert.ok(m, "could not find the `variants` Record literal in badge.tsx");
  // Keys at the start of a line inside the object literal, skipping comments.
  return [...m[1].matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:/gm)].map((x) => x[1]);
}

test("Badge exposes exactly the seven allowed variants", () => {
  assert.deepEqual(
    unionMembers().slice().sort(),
    EXPECTED.slice().sort(),
    "The BadgeVariant union changed. The 7-variant palette is deliberate: each maps to a " +
      "semantic token (bull/bear/warn/info/neutral) or a provenance marker (live/static). " +
      "Adding an eighth means a new visual meaning operators must learn -- justify it, " +
      "do not just widen the union.",
  );
});

test("every declared variant has a style mapping", () => {
  assert.deepEqual(
    variantMapKeys().slice().sort(),
    unionMembers().slice().sort(),
    "badge.tsx's `variants` map and its BadgeVariant union disagree. A union member with no " +
      "mapping renders with `undefined` classes -- an invisible badge, not a compile error.",
  );
});

test("provenance variants live and static are both present", () => {
  // These two carry honesty semantics: `live` = freshly fetched, `static` =
  // placeholder/stale/not-wired. Losing either silently removes the operator's
  // only visual cue that a number may not be real.
  for (const v of ["live", "static"]) {
    assert.ok(
      unionMembers().includes(v),
      `Badge variant "${v}" was removed. It marks data provenance; without it a stale or ` +
        `placeholder value renders indistinguishably from a live one.`,
    );
  }
});
