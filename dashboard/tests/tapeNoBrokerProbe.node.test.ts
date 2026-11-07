import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(new URL('../lib/tape/ibStatus.ts', import.meta.url), 'utf8');
test('tape status never initiates broker,process,config,or engine probes', async () => {
 // Fail BEFORE importing/exercising the module if a probing implementation returns.
 assert.doesNotMatch(source, /from\s+["'](?:node:)?(?:net|fs(?:\/promises)?|child_process)["']|\bfetch\s*\(|\bexecFile\s*\(|\bnet\.connect\s*\(/);
 const {readIbStatus} = await import('../lib/tape/ibStatus.ts');
 const value=await readIbStatus();
 assert.equal(value.light,'amber');
 assert.equal(value.probed,false);
 assert.equal(value.checkedAt,null);
 assert.ok(value.checks.length>0);
 assert.ok(value.checks.every(c=>c.ok===null));
 assert.match(value.checks[0].value,/not checked/i);
});
