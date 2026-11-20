// Wiring/contract lock for the Saty ATR Pro context exposed through AuctionBiasCard.
// This is a read-only decision-support surface; it must never grow order/risk controls.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

const DASHBOARD = process.cwd();

function read(rel: string): string {
  return readFileSync(path.join(DASHBOARD, rel), "utf8");
}

test("auction bias API type exposes Saty ATR Pro fields", () => {
  const src = read("lib/api.ts");
  assert.match(src, /trigger_state\?:/);
  assert.match(src, /range_state\?:/);
  assert.match(src, /chase_risk\?:/);
  assert.match(src, /atr_displacement\?:/);
  assert.match(src, /context_score\?:/);
  assert.match(src, /next_levels\?:/);
});

test("auction bias card renders Saty ATR Pro context and stays read-only", () => {
  const card = read("components/AuctionBiasCard.tsx");
  assert.match(card, /Saty ATR Pro context/);
  assert.match(card, /CHASE RISK/);
  assert.match(card, /Displacement/);
  assert.match(card, /Range state/);
  assert.match(card, /Trigger state/);
  assert.match(card, /neutral read-only map, not an execution signal/);
  assert.ok(!card.includes("postEngine"), "AuctionBiasCard must never POST to the engine");
  assert.doesNotMatch(card, /\/orders|\/approval|\/safety|\/risk/);
});

test("engine auction bias payload includes Saty ATR Pro context fields", () => {
  const src = read("../engine/analysis/auction_bias.py");
  assert.match(src, /saty_atr_context/);
  assert.match(src, /"trigger_state"/);
  assert.match(src, /"range_state"/);
  assert.match(src, /"chase_risk"/);
  assert.match(src, /"atr_displacement"/);
  assert.match(src, /"context_score"/);
  assert.match(src, /"next_levels"/);
});
