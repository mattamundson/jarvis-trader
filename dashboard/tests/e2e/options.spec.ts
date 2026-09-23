import { test, expect } from "@playwright/test";

<<<<<<< HEAD
test("options smoke: renders options automation shell under mocked engine", async ({ page }) => {
=======
test("options smoke: renders readiness truth copy under mocked engine", async ({ page }) => {
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/options", { waitUntil: "domcontentloaded" });

  const body = (await page.textContent("body")) || "";
<<<<<<< HEAD
  expect(body).toContain("Options Automation");
=======
  expect(body).toContain("Options Readiness Surface");
  expect(body).toContain("Mode: readiness surface");
  expect(body).toContain("heuristic estimate, not live executable quote");
  expect(body).not.toContain("Options Automation");
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
  expect(body).not.toMatch(/something went wrong/i);
});
