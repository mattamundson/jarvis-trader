import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Dedicated hermetic fixture server. Never read personal tape state or credentials.
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'jarvis-tape-fixture-'));
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'tests/fixtures/tape/tape-idle-market-closed-20261107.json'),'utf8'));
const raw={...fixture.snapshot,recorder:{state:'idle (fixture)',heartbeat_age_s:2,last_tick_age_s:null},session:{trading_day:'2026-11-07'},levels_source:'tape-plan dated 2026-11-03'};
fs.writeFileSync(path.join(dir,'flow.json'),JSON.stringify(raw));
fs.writeFileSync(path.join(dir,'plan.json'),JSON.stringify(fixture.plan));
fs.writeFileSync(path.join(dir,'gex.json'),JSON.stringify(fixture.gex));
const baseURL='http://127.0.0.1:3015';
export default defineConfig({
 testDir:'./tests/e2e',testMatch:'tape-truthfulness.spec.ts',timeout:30000,
 workers:1,retries:0,fullyParallel:false,
 outputDir:process.env.PW_TAPE_OUTPUT || 'test-results-tape',
 reporter:[['list']],
 use:{baseURL,trace:'off'},
 webServer:{command:'node node_modules/next/dist/bin/next start -p 3015 -H 127.0.0.1',url:baseURL,timeout:120000,reuseExistingServer:false,
  env:{TAPE_FLOW_FILE:path.join(dir,'flow.json'),TAPE_FLOW_FALLBACK_FILE:path.join(dir,'flow.json'),
   TAPE_GEX_FILE:path.join(dir,'gex.json'),TAPE_GEX_FALLBACK_FILE:path.join(dir,'gex.json'),TAPE_PLAN_FILE:path.join(dir,'plan.json'),
   ENGINE_INTERNAL_URL:'http://127.0.0.1:9',ENGINE_URL_INTERNAL:'http://127.0.0.1:9',MASTER_API_URL:'http://127.0.0.1:9',
   NEXT_PUBLIC_ENGINE_URL:'http://127.0.0.1:9',NEXT_PUBLIC_WS_URL:'ws://127.0.0.1:9',
   DASHBOARD_AUTH_USER:'',DASHBOARD_AUTH_PASS:'',ENGINE_API_KEY:'',MASTER_API_KEY:''}},
});
