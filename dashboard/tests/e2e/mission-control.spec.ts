import { test, expect } from "@playwright/test";

test("mission-control smoke: renders mission control shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/mission-control", { waitUntil: "domcontentloaded" });

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("MISSION CONTROL");
  expect(body).not.toMatch(/something went wrong/i);
});
