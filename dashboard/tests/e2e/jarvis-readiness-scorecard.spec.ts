import { test, expect } from "@playwright/test";

test("jarvis page renders readiness scorecard split badges", async ({ page }) => {
  await page.route("**/api/engine/**", (route) =>
    route.fulfill({ status: 503, json: { detail: "engine unavailable in smoke" } })
  );

  await page.goto("/jarvis");

  await expect(page.getByText("Readiness Scorecard")).toBeVisible();
  await expect(page.getByText("operator analysis ready")).toBeVisible();
  await expect(page.getByText("monitoring degraded")).toBeVisible();
  await expect(page.getByText("execution blocked")).toBeVisible();
  await expect(page.getByText("recommendation linked")).toBeVisible();
  await expect(page.getByText("queue lineage gap")).toBeVisible();
  await expect(page.getByText("edge not certified")).toBeVisible();
  await expect(page.getByText("Baseline delta")).toBeVisible();
  await expect(page.getByText("$6,336")).toBeVisible();
  await expect(page.getByText("62")).toBeVisible();
  await expect(page.getByText("$4,759")).toBeVisible();
  await expect(page.getByText("Read-only scorecard")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/something went wrong/i);
});
