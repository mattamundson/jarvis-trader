import { test, expect } from "@playwright/test";

// P5.2: flagship (/command-center, per P2.1's `/` -> `/command-center` dissolve)
// golden path under degraded engine data, plus a security assertion that the
// server-only ENGINE_API_KEY (injected by app/api/engine/[...path]/route.ts)
// never reaches the browser -- no request header, no page source leak.
const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

test("flagship /command-center survives degraded engine data without white-screening", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: { MES: { symbol: "MES", ...NULL_PRICE }, MGC: { symbol: "MGC", ...NULL_PRICE } },
      });
    }
    // These three feed .slice()/.map() array consumers (decisions, trades,
    // scheduler.jobs on app/command-center/page.tsx) -- an empty-object
    // catch-all response is not a realistic degraded shape for them (the
    // real engine returns [] / {jobs: []} on no data), so mock the real
    // contract rather than tripping an unrelated "t.slice is not a
    // function" crash the blanket {} catch-all would otherwise cause.
    if (u.includes("/decisions/recent") || u.includes("/portfolio/history/trades")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (u.includes("/scheduler/status")) {
      return route.fulfill({ status: 200, json: { jobs: [] } });
    }
    // JournalTradeStats.diagnosis is a required non-nullable field the page
    // renders unconditionally (guarded only on `!journalStats`, not on the
    // shape of a truthy-but-empty response) -- an empty-object catch-all is
    // not a realistic 200 for this endpoint, so mock the real "no trades
    // yet" shape instead of tripping an unrelated undefined.replace() crash.
    if (u.includes("/journal/review/stats")) {
      return route.fulfill({
        status: 200,
        json: {
          total_trades: 0,
          win_rate: 0,
          avg_win_usd: 0,
          avg_loss_usd: 0,
          risk_reward_ratio: 0,
          expected_value_usd: 0,
          trades_per_week: 0,
          diagnosis: "insufficient_data",
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/command-center", { waitUntil: "networkidle" });
  const body = (await page.textContent("body")) || "";

  expect(body, "flagship header did not render").toContain("COMMAND CENTER");
  // Page did not collapse to the route-level error fallback (no white-screen).
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
});

test("no engine API key reaches the browser (request headers or page source)", async ({ page }) => {
  const leakedHeaderRequests: string[] = [];
  page.on("request", (request) => {
    const headers = request.headers();
    if (Object.keys(headers).some((h) => h.toLowerCase() === "x-api-key")) {
      leakedHeaderRequests.push(request.url());
    }
  });

  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/command-center", { waitUntil: "networkidle" });

  expect(leakedHeaderRequests, "a browser-originated request carried an X-API-Key header").toEqual([]);

  // The server injects the key server-side only (lib/api.ts:8-10 / the proxy
  // route) -- it must never be inlined into SSR HTML or the client bundle.
  const html = await page.content();
  expect(html, "ENGINE_API_KEY env var name leaked into page source").not.toContain("ENGINE_API_KEY");
  expect(html, "the documented dev-placeholder engine key leaked into page source").not.toContain(
    "jarvis-dev-key-change-me"
  );
});
