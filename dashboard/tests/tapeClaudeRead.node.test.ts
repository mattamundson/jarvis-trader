import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  SIGNAL_NOT_A_FILL,
  claudeReadFreshness,
  findPrivateKeys,
  gammaFreshness,
  parseClaudeRead,
} from "@/lib/tape/claudeRead";
import { loadClaudeRead, tapeStateDir } from "@/lib/tape/claudeReadLoad";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LEAKS = JSON.parse(readFileSync(path.join(HERE, "fixtures/tape/claude-read-with-leaks.json"), "utf8"));
const EXAMPLE = JSON.parse(readFileSync(path.join(HERE, "../../docs/tape/claude-read-latest.example.json"), "utf8"));
const SENTINELS = [
  "SENTINEL_R_TOP", "SENTINEL_R_UPPER", "SENTINEL_PNL_1234", "SENTINEL_PL", "SENTINEL_FILL_BUY_1_MES",
  "SENTINEL_POSITION_LONG_2", "SENTINEL_ACCOUNT_DU", "SENTINEL_UNKNOWN_KEY", "SENTINEL_R_PRIOR",
  "SENTINEL_PNL_GAMMA", "SENTINEL_ACCOUNT_NESTED", "SENTINEL_FILL_LEVEL", "SENTINEL_R_VALUE",
  "SENTINEL_PL_TRIGGER", "SENTINEL_PNL_TRIGGER",
];
const PRIVATE_KEY = /^(r|pnl|p&l|p_l|pl|fill|fills|position|positions|account|equity|balance|cash|margin|unrealized|realized|netliq|net_liq|buying_power|order_id|orderid)$/i;

function keyNames(value: unknown, out: string[] = []): string[] {
  if (Array.isArray(value)) value.forEach((item) => keyNames(item, out));
  else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      out.push(key);
      keyNames(child, out);
    }
  }
  return out;
}

const at = (iso: string) => Date.parse(iso);

test("allow-list drops private keys, R/pnl/fill/pl, and unknown keys", () => {
  const parsed = parseClaudeRead(LEAKS);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  const json = JSON.stringify(parsed.read);
  for (const sentinel of SENTINELS) assert.equal(json.includes(sentinel), false, sentinel);
  assert.equal(json.includes("$"), false);
  for (const key of keyNames(parsed.read)) assert.equal(PRIVATE_KEY.test(key), false, key);
  assert.deepEqual(findPrivateKeys(parsed.read), []);
  assert.equal(parsed.read.context.prior_sessions[0].close, 7640.5);
  assert.equal(parsed.read.context.prior_sessions[0].low, 7600);
  assert.equal(parsed.read.levels[0].price, 7629);
  assert.equal(parsed.read.levels[0].label, "prior shelf");
  assert.equal(parsed.read.triggers[0].status, "armed");
  assert.equal(parsed.read.triggers[0].closes_needed, 2);
  assert.equal(parsed.read.live_legal, "NO, size 0");
  assert.equal(parsed.read.kind, "plan");
});

test("dollar amounts and pnl words in allowed strings are dropped", () => {
  const parsed = parseClaudeRead({ ...EXAMPLE, plan: "risk $500", bias: "pnl 1.2", note: "net liq 10" });
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.read.plan, null);
  assert.equal(parsed.read.bias, null);
  assert.equal(parsed.read.note, null);
  const json = JSON.stringify(parsed.read);
  assert.equal(json.includes("$500"), false);
  assert.equal(json.includes("pnl"), false);
  assert.deepEqual(findPrivateKeys(parsed.read), []);
});

test("example schema parses and keeps the context block", () => {
  const parsed = parseClaudeRead(EXAMPLE);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.read.version, 1);
  assert.equal(parsed.read.source, "claude");
  assert.equal(parsed.read.context.vix_regime, "elevated");
  assert.equal(parsed.read.context.event_implied_move, "CPI day, about 40 pts");
  assert.equal(parsed.read.context.gamma?.regime, "short");
  assert.equal(parsed.read.context.gamma?.flip, 7660.75);
  assert.equal(parsed.read.context.gamma?.pin, 7676);
  assert.deepEqual(parsed.read.context.stale, ["gex vendor print"]);
  assert.equal(parsed.read.plan?.includes("7635.5"), true);
});

test("missing version, bad kind, and broken JSON are malformed rather than thrown", () => {
  assert.equal(parseClaudeRead({}).ok, false);
  assert.equal(parseClaudeRead({ ...EXAMPLE, kind: "order" }).ok, false);
  assert.equal(parseClaudeRead({ ...EXAMPLE, version: 2 }).ok, false);
  assert.equal(parseClaudeRead({ ...EXAMPLE, written_at: "not-a-time" }).ok, false);
});

test("staleness: 60 minutes during RTH is current, anything older is stale", () => {
  const now = at("2026-11-12T10:00:00-06:00");
  const exact = claudeReadFreshness("2026-11-12T09:00:00-06:00", now);
  assert.equal(exact.duringRth, true);
  assert.equal(exact.stale, false);
  assert.equal(exact.writtenAtCt, "2026-11-12 09:00 CT");
  const older = claudeReadFreshness("2026-11-12T08:59:59-06:00", now);
  assert.equal(older.stale, true);
  assert.match(older.reason, /RTH/);
  const open = claudeReadFreshness("2026-11-12T08:00:00-06:00", at("2026-11-12T08:30:00-06:00"));
  assert.equal(open.duringRth, true);
  assert.equal(open.stale, false);
  const beforeOpen = claudeReadFreshness("2026-11-12T06:00:00-06:00", at("2026-11-12T08:29:00-06:00"));
  assert.equal(beforeOpen.duringRth, false);
});

test("outside RTH, stale means a different Globex trading day, not file age", () => {
  const premarket = at("2026-11-12T07:00:00-06:00");
  const sameDay = claudeReadFreshness("2026-11-12T06:00:00-06:00", premarket);
  assert.equal(sameDay.duringRth, false);
  assert.equal(sameDay.stale, false);
  assert.equal(sameDay.writtenTradingDay, "2026-11-12");
  const priorDay = claudeReadFreshness("2026-11-11T14:00:00-06:00", premarket);
  assert.equal(priorDay.stale, true);
  assert.equal(priorDay.writtenTradingDay, "2026-11-11");
  assert.equal(priorDay.currentTradingDay, "2026-11-12");

  const sundayEvening = at("2026-11-08T18:00:00-06:00");
  const globex = claudeReadFreshness("2026-11-08T17:30:00-06:00", sundayEvening);
  assert.equal(globex.duringRth, false);
  assert.equal(globex.currentTradingDay, "2026-11-09");
  assert.equal(globex.writtenTradingDay, "2026-11-09");
  assert.equal(globex.stale, false);

  const afterClose = claudeReadFreshness("2026-11-12T14:00:00-06:00", at("2026-11-12T15:01:00-06:00"));
  assert.equal(afterClose.duringRth, false);
  assert.equal(afterClose.stale, false);
  const atClose = claudeReadFreshness("2026-11-12T13:00:00-06:00", at("2026-11-12T15:00:00-06:00"));
  assert.equal(atClose.duringRth, true);
  assert.equal(atClose.stale, true);
});

test("gamma age is flagged only after 60 minutes", () => {
  const now = at("2026-11-12T10:00:00-06:00");
  const fresh = gammaFreshness("2026-11-12T09:40:00-06:00", now);
  assert.equal(fresh.stale, false);
  assert.equal(fresh.ageMinutes, 20);
  const exact = gammaFreshness("2026-11-12T09:00:00-06:00", now);
  assert.equal(exact.stale, false);
  const old = gammaFreshness("2026-11-12T08:49:00-06:00", now);
  assert.equal(old.stale, true);
  assert.match(old.reason, /60 min/);
  const missing = gammaFreshness(null, now);
  assert.equal(missing.stale, true);
  assert.match(missing.reason, /missing/);
});

test("loader reports a missing or malformed file and strips leaks from a real fixture", async () => {
  const missingDir = await mkdtemp(path.join(os.tmpdir(), "claude-read-missing-"));
  const missing = await loadClaudeRead(missingDir, at("2026-11-12T08:20:00-06:00"));
  assert.equal(missing.missing, true);
  assert.equal(missing.malformed, false);
  assert.equal(missing.read, null);
  assert.match(missing.error ?? "", /not in the tape state folder/);

  const badDir = await mkdtemp(path.join(os.tmpdir(), "claude-read-bad-"));
  await writeFile(path.join(badDir, "claude-read-latest.json"), "{", "utf8");
  const bad = await loadClaudeRead(badDir, at("2026-11-12T08:20:00-06:00"));
  assert.equal(bad.malformed, true);
  assert.equal(bad.read, null);

  const okDir = await mkdtemp(path.join(os.tmpdir(), "claude-read-ok-"));
  await writeFile(path.join(okDir, "claude-read-latest.json"), JSON.stringify(LEAKS), "utf8");
  const loaded = await loadClaudeRead(okDir, at("2026-11-12T08:40:00-06:00"));
  assert.equal(loaded.ok, true);
  assert.equal(loaded.freshness?.stale, false);
  assert.equal(loaded.freshness?.duringRth, true);
  assert.equal(loaded.gamma?.present, true);
  assert.equal(loaded.gamma?.stale, false);
  const json = JSON.stringify(loaded);
  for (const sentinel of SENTINELS) assert.equal(json.includes(sentinel), false, sentinel);

  const noGamma = await loadClaudeRead(okDir, at("2026-11-12T08:40:00-06:00"));
  assert.equal(noGamma.gamma?.present, true);
  const bareDir = await mkdtemp(path.join(os.tmpdir(), "claude-read-nogamma-"));
  const bare = { ...EXAMPLE, context: { ...EXAMPLE.context, gamma: undefined } };
  delete bare.context.gamma;
  await writeFile(path.join(bareDir, "claude-read-latest.json"), JSON.stringify(bare), "utf8");
  const without = await loadClaudeRead(bareDir, at("2026-11-12T08:20:00-06:00"));
  assert.equal(without.ok, true);
  assert.equal(without.gamma?.present, false);
  assert.equal(without.gamma?.stale, false);
});

test("state directory is TAPE_STATE_DIR, else ~/tape/state", () => {
  assert.equal(tapeStateDir({ TAPE_STATE_DIR: "/var/tape-state" } as NodeJS.ProcessEnv), "/var/tape-state");
  assert.equal(tapeStateDir({ HOME: "/tmp/tapehome", USERPROFILE: "" } as NodeJS.ProcessEnv), path.join("/tmp/tapehome", "tape", "state"));
});

test("trigger surfaces use the exact signal label", () => {
  assert.equal(SIGNAL_NOT_A_FILL, "signal, not a fill");
  const root = path.resolve(HERE, "..");
  for (const rel of [
    "components/tape/ClaudeReadPanel.tsx",
    "app/tape/page.tsx",
    "app/tape/lean/page.tsx",
    "components/tape/TapeExtras.tsx",
  ]) {
    const src = readFileSync(path.join(root, rel), "utf8");
    assert.equal(src.includes("SIGNAL_NOT_A_FILL"), true, rel);
    assert.equal(src.includes("writeFile"), false, rel);
  }
  const route = readFileSync(path.join(root, "app/api/tape/claude-read/route.ts"), "utf8");
  assert.equal(/writeFile|appendFile|placeOrder|child_process/.test(route), false);
});

test("example file on disk matches the committed fixture the loader accepts", async () => {
  const text = await readFile(path.join(HERE, "../../docs/tape/claude-read-latest.example.json"), "utf8");
  const dir = await mkdtemp(path.join(os.tmpdir(), "claude-read-example-"));
  await writeFile(path.join(dir, "claude-read-latest.json"), text, "utf8");
  const loaded = await loadClaudeRead(dir, at("2026-11-12T08:20:00-06:00"));
  assert.equal(loaded.ok, true);
  assert.equal(loaded.read?.kind, "plan");
  assert.equal(loaded.freshness?.writtenAtCt, "2026-11-12 08:05 CT");
});
