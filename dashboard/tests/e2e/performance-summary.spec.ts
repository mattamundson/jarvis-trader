import { test, expect, type Page } from "@playwright/test";

// /performance summary-first workspace (PRB dashboard-hardening Task 3).
// Mirrors the validation-workspace assertions added to trading-eligibility.spec.ts:
// initial summary heading, section navigation, deep-link loading, and DOM
// absence of a non-selected heavy section.

function mockEngineForPerformance(page: Page) {
  return page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));
}

test.describe("performance workspace sections", () => {
  test("defaults to the summary (account truth) section and does not mount a heavy drill-down section", async ({ page }) => {
    await mockEngineForPerformance(page);
    await page.goto("/performance", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: /Backtest Performance Analytics/i })).toBeVisible();
    await expect(page.getByTestId("performance-section-summary")).toBeVisible();
    await expect(page.getByTestId("performance-section-research")).toHaveCount(0);
    await expect(page.getByTestId("performance-section-execution")).toHaveCount(0);
  });

  test("selecting the research section via the workspace nav mounts only that section", async ({ page }) => {
    await mockEngineForPerformance(page);
    await page.goto("/performance", { waitUntil: "domcontentloaded" });

    await page.getByTestId("performance-section-tab-research").click();
    await expect(page).toHaveURL(/[?&]section=research/);
    await expect(page.getByTestId("performance-section-research")).toBeVisible();
    await expect(page.getByTestId("performance-section-summary")).toHaveCount(0);
  });

  test("deep-linking directly to a section loads it without visiting summary first", async ({ page }) => {
    await mockEngineForPerformance(page);
    await page.goto("/performance?section=execution", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("performance-section-execution")).toBeVisible();
    await expect(page.getByTestId("performance-section-summary")).toHaveCount(0);
  });

  test("browser back navigation restores the previous section", async ({ page }) => {
    await mockEngineForPerformance(page);
    await page.goto("/performance", { waitUntil: "domcontentloaded" });

    await page.getByTestId("performance-section-tab-risk").click();
    await expect(page).toHaveURL(/[?&]section=risk/);
    await expect(page.getByTestId("performance-section-risk")).toBeVisible();

    await page.goBack();
    await expect(page.getByTestId("performance-section-summary")).toBeVisible();
    await expect(page.getByTestId("performance-section-risk")).toHaveCount(0);
  });

  test("an unrecognized section id falls back to summary instead of crashing", async ({ page }) => {
    await mockEngineForPerformance(page);
    await page.goto("/performance?section=bogus", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("performance-section-summary")).toBeVisible();
    const body = (await page.textContent("body")) || "";
    expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
  });
});
