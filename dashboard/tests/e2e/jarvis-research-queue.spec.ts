import { test, expect } from "@playwright/test";

test("jarvis page renders x-bookmarks research queue feed", async ({ page }) => {
  await page.route("**/api/engine/**", (route) =>
    route.fulfill({ status: 503, json: { detail: "engine unavailable in smoke" } })
  );

  await page.goto("/jarvis");

  await expect(page.getByText("X-Bookmarks Research Queue")).toBeVisible();
  await expect(page.getByRole("button", { name: /Risk \/ Sizing\s*\(10\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Strategy \/ Indicators\s*\(10\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Validation Integrity\s*\(2\)/ })).toBeVisible();
  await expect(page.getByText("Paper-only research candidates")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/something went wrong/i);
});
