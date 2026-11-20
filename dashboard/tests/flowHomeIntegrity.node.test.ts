import { test } from 'node:test';
import assert from 'node:assert/strict';
import { analyzeGateAction, biasLabel, isStale, volumePaceRatio } from '../lib/flowTypes.ts';

const gate = {level: 100, status: 'testing' as const, closeCount: null};
test('missing flow evidence is unavailable, not a neutral or bearish observation', () => {
  assert.equal(analyzeGateAction(gate, 101, null, null, null).action, 'UNAVAILABLE');
  assert.equal(analyzeGateAction(gate, 101, 0, null, []).action, 'UNAVAILABLE');
  assert.equal(biasLabel(101, Number.NaN), 'UNAVAILABLE');
  assert.equal(biasLabel(Number.NaN, 100), 'UNAVAILABLE');
});
test('malformed and future source timestamps never pass freshness', () => {
  assert.equal(isStale('malformed'), true);
  assert.equal(isStale(new Date(Date.now() + 60_000).toISOString()), true);
  assert.equal(isStale(new Date(Date.now() - 1_000).toISOString()), false);
});
test('insufficient volume history never invents normal 1.0x pace', () => {
  assert.equal(volumePaceRatio([]), null);
  const bar = {ts:'2026-11-07T18:00:00Z', open:100, high:101, low:99, close:100, volume:10};
  assert.equal(volumePaceRatio([bar]), null);
  assert.equal(volumePaceRatio([{...bar, volume:0}, bar]), null);
  assert.equal(volumePaceRatio([bar, {...bar, volume:20}])?.ratio, 2);
});
test('complete evidence preserves positive gate and bias behavior', () => {
  assert.equal(analyzeGateAction(gate, 98, -100, -100, []).action, 'BREAK');
  assert.equal(analyzeGateAction(gate, 100, 100, 0, [{price:100,bidLots:40,askLots:10}]).action, 'ABSORB');
  assert.equal(analyzeGateAction(gate, 100, 100, 0, []).action, 'NEUTRAL');
  assert.equal(biasLabel(102,100), 'BULL');
  assert.equal(biasLabel(98,100), 'BEAR');
});
