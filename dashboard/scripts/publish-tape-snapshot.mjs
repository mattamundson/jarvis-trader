#!/usr/bin/env node
// Publish /tape snapshots for the Vercel (snapshot-mode) build.
// Reads the local 3010 dashboard GET endpoints (Basic Auth from .env.local,
// never printed), writes data/tape-snapshots/*.json, and with --push commits
// ONLY those two files and pushes the current branch. No engine or order calls.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const envFile = process.env.TAPE_ENV_FILE || "C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\dashboard\\.env.local";
const env = Object.fromEntries(fs.readFileSync(envFile, "utf8").split(/\r?\n/).filter((l) => /^DASHBOARD_AUTH_(USER|PASS)=/.test(l)).map((l) => { const i = l.indexOf("="); return [l.slice(0, i), l.slice(i + 1).trim().replace(/^"|"$/g, "")]; }));
const auth = "Basic " + Buffer.from(`${env.DASHBOARD_AUTH_USER}:${env.DASHBOARD_AUTH_PASS}`).toString("base64");
const base = process.env.TAPE_LOCAL_URL || "http://127.0.0.1:3010";

async function get(p) {
  const r = await fetch(base + p, { headers: { authorization: auth }, signal: AbortSignal.timeout(90000) });
  if (!r.ok) throw new Error(`${p} -> ${r.status}`);
  return r.json();
}

const publishedAt = Date.now();
const flow = await get("/api/flow/tape");
const extras = await get("/api/tape/extras");
const dir = path.join(root, "data", "tape-snapshots");
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, "flow-tape.json"), JSON.stringify({ ...flow, publishedAt, snapshotSource: "PC 3010 publish" }));
fs.writeFileSync(path.join(dir, "tape-extras.json"), JSON.stringify({ ...extras, publishedAt, snapshotSource: "PC 3010 publish" }));
console.log(`wrote snapshots publishedAt=${new Date(publishedAt).toISOString()} flowSource=${flow.source} extras=${Object.keys(extras).join(",")}`);

if (process.argv.includes("--push")) {
  const git = (...a) => execFileSync("git", a, { cwd: root, encoding: "utf8" }).trim();
  git("add", "--", "data/tape-snapshots/flow-tape.json", "data/tape-snapshots/tape-extras.json");
  const staged = git("diff", "--cached", "--name-only");
  if (!staged) { console.log("no change"); process.exit(0); }
  git("commit", "-q", "-m", `tape snapshot ${new Date(publishedAt).toISOString()}`, "--", "data/tape-snapshots/flow-tape.json", "data/tape-snapshots/tape-extras.json");
  const branch = git("rev-parse", "--abbrev-ref", "HEAD");
  git("push", "-q", "origin", branch);
  console.log(`pushed ${git("rev-parse", "--short", "HEAD")} to ${branch}`);
}
