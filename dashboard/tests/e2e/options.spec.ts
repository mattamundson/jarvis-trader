import { test, expect } from "@playwright/test";

test("options smoke: renders readiness truth copy under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/options", { waitUntil: "domcontentloaded" });

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("Options Readiness Surface");
  expect(body).toContain("Mode: readiness surface");
  expect(body).toContain("heuristic estimate, not live executable quote");
  expect(body).not.toContain("Options Automation");
  expect(body).not.toMatch(/something went wrong/i);
});
