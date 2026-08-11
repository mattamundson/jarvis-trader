#!/usr/bin/env node
// Static guards for the dashboard source tree (Phase 1.4).
//
// Runs in CI as part of `dashboard-quality`, and locally via `pnpm run guards`.
// Everything here is a pure text check -- no build, no install beyond node, so it
// is cheap enough to run on every push including drafts.
//
// Each guard below records the violation count measured on master at the time it
// was written. A guard that was already violated could not honestly be made
// blocking on day one, so those ship as ratchets instead -- see REFRESH_INTERVAL.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DASH = join(HERE, "..");

// Same scope as the pre-existing bare-fetch gates in ci.yml, plus lib/ where noted.
const UI_DIRS = ["app", "components", "hooks"];
const ALL_DIRS = ["app", "components", "hooks", "lib"];

// ---------------------------------------------------------------------------
// Comment stripping
//
// A naive "delete from // to end of line" is WRONG here and would silently
// defeat the engine-URL guard: the string "http://127.0.0.1:8010" contains //,
// so naive stripping deletes the URL we are hunting for. This scanner tracks
// string and template literals so only real comments are removed, and replaces
// them with spaces so line/column numbers stay intact.
// ---------------------------------------------------------------------------
function stripComments(src) {
  const out = [...src];
  let i = 0;
  const n = src.length;
  let state = "code"; // code | line | block | sq | dq | tpl
  while (i < n) {
    const c = src[i];
    const d = src[i + 1];
    if (state === "code") {
      if (c === "/" && d === "/") { state = "line"; out[i] = " "; out[i + 1] = " "; i += 2; continue; }
      if (c === "/" && d === "*") { state = "block"; out[i] = " "; out[i + 1] = " "; i += 2; continue; }
      if (c === "'") state = "sq";
      else if (c === '"') state = "dq";
      else if (c === "`") state = "tpl";
      i++; continue;
    }
    if (state === "line") {
      if (c === "\n") { state = "code"; i++; continue; }
      out[i] = " "; i++; continue;
    }
    if (state === "block") {
      if (c === "*" && d === "/") { state = "code"; out[i] = " "; out[i + 1] = " "; i += 2; continue; }
      if (c !== "\n") out[i] = " ";
      i++; continue;
    }
    // inside a string / template literal
    if (c === "\\") { i += 2; continue; }
    if ((state === "sq" && c === "'") || (state === "dq" && c === '"') || (state === "tpl" && c === "`")) {
      state = "code";
    }
    i++;
  }
  return out.join("");
}

function walk(dir, out = []) {
  let entries;
  try { entries = readdirSync(dir); } catch { return out; }
  for (const e of entries) {
    if (e === "node_modules" || e === ".next" || e === ".next-dev") continue;
    const full = join(dir, e);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(e)) out.push(full);
  }
  return out;
}

function collect(dirs) {
  const files = [];
  for (const d of dirs) files.push(...walk(join(DASH, d)));
  return files.map((f) => {
    const rel = relative(DASH, f).split(sep).join("/");
    const raw = readFileSync(f, "utf8");
    return { rel, raw, code: stripComments(raw) };
  });
}

const failures = [];
const notes = [];

function report(name, hits, message) {
  if (hits.length === 0) {
    console.log(`OK   ${name} (0 violations)`);
    return;
  }
  console.log(`FAIL ${name} (${hits.length} violation(s))`);
  for (const h of hits) console.log(`       ${h}`);
  console.log(`       ${message}`);
  failures.push(name);
}

const UI = collect(UI_DIRS);
const ALL = collect(ALL_DIRS);

// ---------------------------------------------------------------------------
// GUARD 1 -- direct engine URL. Measured on master: 2 hits, both allowlisted.
// The dashboard must reach the engine through lib/api.ts -> app/api/engine proxy,
// so a hardcoded host:port in UI code is a deployment landmine.
// ---------------------------------------------------------------------------
const ENGINE_URL_ALLOW = new Map([
  // WebSockets cannot be routed through the Next.js HTTP proxy route, so this
  // module resolves the engine origin directly. Genuine exception, not debt.
  ["lib/engine-websocket-context.tsx", "WS cannot traverse the app/api HTTP proxy"],
  // Display text only -- renders the engine address for the operator to read.
  // It is not used to issue a request.
  ["app/strategy-c/page.tsx", "renders the address as visible text, issues no request"],
]);
{
  const re = /(localhost|127\.0\.0\.1):8010/;
  const hits = [];
  for (const f of ALL) {
    if (f.rel.startsWith("app/api/")) continue; // server infra: the proxy itself
    if (ENGINE_URL_ALLOW.has(f.rel)) continue;
    f.code.split("\n").forEach((line, i) => {
      if (re.test(line)) hits.push(`${f.rel}:${i + 1}: ${line.trim().slice(0, 100)}`);
    });
  }
  report("no-direct-engine-url", hits,
    "Reach the engine via fetchEngine/postEngine (lib/api.ts), which routes through app/api/engine.");
}

// ---------------------------------------------------------------------------
// GUARD 2 -- bare fetch, broadened. The two gates already in ci.yml grep the
// literal "await fetch(", which misses `const p = fetch(...)`, `void fetch(...)`
// and `.then()` chains. This uses \bfetch\s*\( on comment-stripped source.
// Measured on master: 0 real violations (the only 2 raw matches were comments,
// which is exactly why the stripping above is load-bearing).
// ---------------------------------------------------------------------------
{
  const re = /\bfetch\s*\(/;
  const hits = [];
  for (const f of UI) {
    if (f.rel.startsWith("app/api/")) continue;
    f.code.split("\n").forEach((line, i) => {
      if (re.test(line)) hits.push(`${f.rel}:${i + 1}: ${line.trim().slice(0, 100)}`);
    });
  }
  report("no-bare-fetch", hits,
    "Use fetchEngine/postEngine/fetchEngineRaw from lib/api.ts instead of a raw fetch.");
}

// ---------------------------------------------------------------------------
// GUARD 3 -- static import defeating next/dynamic. If a module is lazy-loaded
// via dynamic() but ALSO statically imported as a value in the same file, the
// static import pulls it into the parent chunk and the dynamic() call does
// nothing. `import type` is fine -- type bindings are erased before bundling.
// Measured on master: 0 violations.
// ---------------------------------------------------------------------------
{
  const dynRe = /dynamic\(\s*\(\)\s*=>\s*import\(\s*["']([^"']+)["']/g;
  const statRe = /^\s*import\s+(?!type\s)([^;]*?)\s+from\s+["']([^"']+)["']/gm;
  const hits = [];
  for (const f of ALL) {
    if (!f.code.includes("dynamic(")) continue;
    const dyn = new Set([...f.code.matchAll(dynRe)].map((m) => m[1]));
    if (dyn.size === 0) continue;
    for (const m of f.code.matchAll(statRe)) {
      if (dyn.has(m[2])) hits.push(`${f.rel}: "${m[2]}" is both statically imported and dynamic()-loaded`);
    }
  }
  report("no-dynamic-import-defeated-by-static", hits,
    "Drop the static import, or narrow it to `import type` so the value binding is erased.");
}

// ---------------------------------------------------------------------------
// GUARD 4 -- hardcoded SWR refreshInterval. RATCHET, not a hard gate.
//
// Measured on master: 128 hardcoded call-sites against 3 using POLL_INTERVAL.
// Making this blocking today would fail every PR and force a 128-site refactor
// as a drive-by, so it ships as a ceiling instead: new hardcoded intervals are
// rejected, and Phase 6.4's cleanup lowers the number.
//
// Deliberately does NOT fail when the count drops. During a planned 128 -> 0
// migration, failing on improvement is pure friction; it prints a reminder to
// lower the ceiling instead.
// ---------------------------------------------------------------------------
const REFRESH_INTERVAL_CEILING = 128;
{
  const re = /refreshInterval:\s*[0-9]/;
  let count = 0;
  const sample = [];
  for (const f of ALL) {
    f.code.split("\n").forEach((line, i) => {
      if (re.test(line)) { count++; if (sample.length < 5) sample.push(`${f.rel}:${i + 1}`); }
    });
  }
  if (count > REFRESH_INTERVAL_CEILING) {
    console.log(`FAIL hardcoded-refresh-interval (${count} > ceiling ${REFRESH_INTERVAL_CEILING})`);
    for (const s of sample) console.log(`       ${s}`);
    console.log("       Use a POLL_INTERVAL.* tier from lib/polling-config.ts, not a literal.");
    console.log("       Market-data polls must not exceed POLL_INTERVAL.MARKET_DATA_MAX (5 min).");
    failures.push("hardcoded-refresh-interval");
  } else if (count < REFRESH_INTERVAL_CEILING) {
    console.log(`OK   hardcoded-refresh-interval (${count}, ceiling ${REFRESH_INTERVAL_CEILING})`);
    notes.push(`refreshInterval debt dropped to ${count}; lower REFRESH_INTERVAL_CEILING to lock it in.`);
  } else {
    console.log(`OK   hardcoded-refresh-interval (${count}, at ceiling ${REFRESH_INTERVAL_CEILING})`);
  }
}

console.log("");
for (const n of notes) console.log(`NOTE ${n}`);
if (failures.length > 0) {
  console.error(`\n${failures.length} guard(s) failed: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("All dashboard guards passed.");
