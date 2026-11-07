import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizePlan, planAvailability } from '@/lib/tapePlan';
import { tapeEvaluationAllowed, recorderContext } from '@/lib/tapeFreshnessContract';

test('fresh heartbeat cannot replace an actual tick', () => {
 assert.equal(tapeEvaluationAllowed(true, 1, null, false), false);
 assert.equal(tapeEvaluationAllowed(true, 1, 500, false), false);
 assert.equal(tapeEvaluationAllowed(true, 1, -1, false), false);
 assert.equal(tapeEvaluationAllowed(true, 1, NaN, false), false);
 assert.equal(tapeEvaluationAllowed(true, 1, 1, true), false);
 assert.equal(tapeEvaluationAllowed(true, 1, 1, false), true);
});

test('copying an old snapshot cannot reset actual tick age', () => {
 const r=recorderContext({as_of_epoch:1000,recorder:{last_tick_age_s:10,heartbeat_age_s:2}}, 1_100_000);
 assert.equal(r.lastTickAgeS, 110);
 assert.equal(r.heartbeatAgeS, 102);
 assert.equal(recorderContext({recorder:{last_tick_age_s:0}},1_100_000).lastTickAgeS,null);
 assert.equal(recorderContext({as_of_epoch:1200,recorder:{last_tick_age_s:0}},1_100_000).lastTickAgeS,null);
});

test('Sunday evening accepts the Monday Globex plan, not Sunday calendar date', () => {
 const p=normalizePlan({date:'2026-11-09',long:{trigger:100,minDelta:0,targets:[110],stop:95}});
 const a=planAvailability(p,{todayCt:'2026-11-08',globexTradingDate:'2026-11-09',recorderSessionTradingDay:'2026-11-09',recorderLevelsSource:'tape-plan dated 2026-11-09'});
 assert.equal(a.usable,true,a.reason);
});
