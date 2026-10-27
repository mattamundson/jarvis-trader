import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Build guard for /tape: the page, its components, its API route and everything they import
// (transitively, through the dashboard's own modules) must stay free of P&L / position /
// account / trading-engine surfaces. If a future change wires one in, this fails.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const FORBIDDEN_MODULE = /pnl|(^|[\\/._-])(position|positions|portfolio|account|accounts|paper|trades?|orders?|broker|ibkr|execution|performance|journal|equity|risk|kill-?switch|engine-api|engine-websocket|master)([\\/._-]|$)/i;
const FORBIDDEN_FETCH = /\/api\/(engine|portfolio|positions?|paper|account|accounts|trades?|orders?|performance|master|pnl)\b/i;
const FORBIDDEN_IMPORT_ALLOWLIST = new Set<string>([]);

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((n) => {
    const p = path.join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

function resolveSpecifier(spec: string, from: string): string | null {
  let base: string | null = null;
  if (spec.startsWith("@/")) base = path.join(root, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(from), spec);
  if (!base) return null; // bare package (react, swr, next/server, node:*) -- external
  for (const c of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts"), path.join(base, "index.tsx")]) {
    if (existsSync(c) && statSync(c).isFile()) return c;
  }
  return base; // unresolved local path: still judged by name
}

const IMPORT_RE = /(?:import|export)\s+(?:type\s+)?(?:[^'"]*?from\s+)?["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)|require\(\s*["']([^"']+)["']\s*\)/g;

export function scanTapeGraph(entries: string[]): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  const queue = [...entries];
  while (queue.length) {
    const file = queue.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    if (!existsSync(file)) continue;
    const src = readFileSync(file, "utf8");
    const rel = path.relative(root, file).replace(/\\/g, "/");
    if (FORBIDDEN_FETCH.test(src)) problems.push(`${rel}: fetches a private API path`);
    for (const m of src.matchAll(IMPORT_RE)) {
      const spec = m[1] ?? m[2] ?? m[3];
      if (!spec) continue;
      const target = resolveSpecifier(spec, file);
      if (!target) {
        // external package: block engine-ish bare names only
        if (/^(@?ib[-_]|ib_async)/i.test(spec)) problems.push(`${rel}: imports ${spec}`);
        continue;
      }
      const targetRel = path.relative(root, target).replace(/\\/g, "/");
      if (!FORBIDDEN_IMPORT_ALLOWLIST.has(targetRel) && FORBIDDEN_MODULE.test(targetRel)) problems.push(`${rel}: imports ${spec} (${targetRel})`);
      if (existsSync(target) && statSync(target).isFile()) queue.push(target);
    }
  }
  return problems;
}

function tapeEntries(): string[] {
  return [
    path.join(root, "app", "tape", "page.tsx"),
    path.join(root, "app", "api", "tape", "route.ts"),
    ...walk(path.join(root, "app", "tape")),
    ...walk(path.join(root, "components", "tape")),
    ...walk(path.join(root, "lib", "tape")),
  ].filter((f) => /\.(ts|tsx)$/.test(f));
}

test("tape entry points exist (guard is not vacuous)", () => {
  const e = tapeEntries();
  assert.ok(e.some((f) => f.endsWith(path.join("app", "tape", "page.tsx"))));
  assert.ok(e.some((f) => f.endsWith(path.join("app", "api", "tape", "route.ts"))));
  assert.ok(e.length >= 8, `expected the tape tree, found ${e.length} files`);
});

test("/tape and /api/tape import no P&L / position / account / engine modules (transitive)", () => {
  assert.deepEqual(scanTapeGraph(tapeEntries()), []);
});

test("guard self-check: a tape file importing a position/P&L module would be caught", async () => {
  const { mkdtempSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const dir = mkdtempSync(path.join(tmpdir(), "tape-guard-"));
  const bad = path.join(dir, "bad.tsx");
  writeFileSync(bad, `import { usePositions } from "@/lib/positions";\nimport { x } from "@/components/PnlCard";\nfetch("/api/engine/positions");\n`);
  const problems = scanTapeGraph([bad]);
  assert.ok(problems.length >= 3, `expected 3 problems, got ${JSON.stringify(problems)}`);
});
