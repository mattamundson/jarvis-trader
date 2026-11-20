import { test, expect } from '@playwright/test';
function fixture() {
 // Synthetic home FlowSnapshot (not the different TapeSnapshot schema).
 return {ts:new Date().toISOString(),fixture:false,
  es:{last:100,vwap:null,onHigh:null,onLow:null,cvd:null,cvdLow:null,
      bars1m:[],deltaAtPrice:null,bigPrints:null},
  nq:{last:null,vwap:null},
  gex:{callWall:null,putWall:null,flip:null,pin:null,asOf:null},
  gates:[{level:100,status:'pending',closeCount:null}]};
}
test.beforeEach(async ({page})=>{
 await page.route('**/api/**',r=>r.fulfill({status:503,contentType:'application/json',body:'{"error":"isolated"}'}));
 await page.routeWebSocket('**/*',s=>s.close());
});
test('master home renders null fields as unavailable, not neutral analysis',async({page})=>{
 const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message));
 const body=fixture();
 await page.route('**/api/flow',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
 await page.goto('/');
 await expect(page.getByTestId('flow-page-header')).toBeVisible();
 await expect(page.getByText('Gate Actions',{exact:true}).locator('..')).toContainText('UNAVAILABLE');
 await expect(page.getByTestId('flow-delta-ladder')).toContainText('UNAVAILABLE');
 await expect(page.getByTestId('flow-gate-levels')).toContainText('closes UNAVAILABLE');
 expect(errors).toEqual([]);
});
for (const stale of [false, true]) {
 test(`master home complete evidence ${stale ? 'stale: withheld' : 'fresh: evaluated'}`,async({page})=>{
  const body={...fixture(),ts:new Date(Date.now()-(stale ? 120_000 : 0)).toISOString(),
   es:{last:98,vwap:100,onHigh:102,onLow:97,cvd:-100,cvdLow:-100,bars1m:[],deltaAtPrice:[],bigPrints:[]},
   nq:{last:100,vwap:100}};
  await page.route('**/api/flow',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
  await page.goto('/');
  const actions=page.getByText('Gate Actions',{exact:true}).locator('..');
  await expect(actions).toContainText(stale ? 'UNAVAILABLE' : 'BREAK');
  if (stale) await expect(actions).not.toContainText('BREAK');
 });
}

test('master home future clock cannot claim LIVE or evaluate gates',async({page})=>{
 const body=fixture();body.ts=new Date(Date.now()+60_000).toISOString();
 await page.route('**/api/flow',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
 await page.goto('/');
 await expect(page.getByText('CVD UNAVAILABLE',{exact:true})).toBeVisible();
 await expect(page.getByText('● LIVE',{exact:true})).toHaveCount(0);
 await expect(page.getByText('Gate Actions',{exact:true}).locator('..')).toContainText('UNAVAILABLE');
});
