import { test, expect } from "@playwright/test";

const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

test("pending-approvals smoke: renders approvals shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/trades/pending")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades/pending-approvals", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Pending trade approvals/i })).toBeVisible();
  await expect(page.getByText(/pending/i).first()).toBeVisible();
});
