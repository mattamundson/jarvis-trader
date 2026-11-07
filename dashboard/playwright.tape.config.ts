import { defineConfig } from '@playwright/test';
import { tapeFixtureEnv } from './tests/fixtures/tape/serverEnv';

// Dedicated hermetic fixture server. Never use production state/credentials.
const fixtureEnv=tapeFixtureEnv();
const baseURL='http://127.0.0.1:3015';
export default defineConfig({
 testDir:'./tests/e2e',testMatch:['tape-truthfulness.spec.ts','flow-home-integrity.spec.ts','tape-secondary-integrity.spec.ts'],timeout:30000,
 workers:1,retries:0,fullyParallel:false,
 outputDir:process.env.PW_TAPE_OUTPUT || 'test-results-tape',
 reporter:[['list']],
 use:{baseURL,trace:'off'},
 webServer:{command:'node node_modules/next/dist/bin/next start -p 3015 -H 127.0.0.1',url:baseURL,timeout:120000,reuseExistingServer:false,
  env:{...fixtureEnv,
   // All file-reader inputs, including proof, are pinned by the shared fixture helper.
   ENGINE_INTERNAL_URL:'http://127.0.0.1:9',ENGINE_URL_INTERNAL:'http://127.0.0.1:9',MASTER_API_URL:'http://127.0.0.1:9',
   NEXT_PUBLIC_ENGINE_URL:'http://127.0.0.1:9',NEXT_PUBLIC_WS_URL:'ws://127.0.0.1:9',
   DASHBOARD_AUTH_USER:'',DASHBOARD_AUTH_PASS:'',ENGINE_API_KEY:'',MASTER_API_KEY:''}},
});
