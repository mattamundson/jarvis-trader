import { test, expect } from "@playwright/test";

test("trade-history smoke: renders trade history shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/portfolio/history/trades") || url.includes("/paper/trades")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades", { waitUntil: "domcontentloaded" });
  const body = (await page.textContent("body")) || "";
  expect(body).toContain("Trade History");
  expect(body).not.toMatch(/something went wrong/i);
});
