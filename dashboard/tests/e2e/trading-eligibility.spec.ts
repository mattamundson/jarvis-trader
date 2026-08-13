import { test, expect, type Page } from "@playwright/test";

test("trading-eligibility smoke: renders eligibility shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/paper/validation/approved-paper-gates")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trading-eligibility", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Trading Eligibility/i })).toBeVisible();
});

// /validation summary-first workspace (PRB dashboard-hardening Task 3). Reuses
// this file (rather than a dedicated spec) because both pages share the same
// approved-paper-gates mock shape as the smoke test above.
function mockEngineForValidation(page: Page) {
  return page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/paper/validation/approved-paper-gates")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (url.includes("/backtest/results")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });
}

test.describe("validation workspace sections", () => {
  test("defaults to the summary section and does not mount a heavy drill-down section", async ({ page }) => {
    await mockEngineForValidation(page);
    await page.goto("/validation", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: /Strategy Validation Dashboard/i })).toBeVisible();
    await expect(page.getByTestId("validation-section-summary")).toBeVisible();
    await expect(page.getByTestId("validation-section-wfe")).toHaveCount(0);
    await expect(page.getByTestId("validation-section-reconciliation")).toHaveCount(0);
    await expect(page.getByTestId("validation-section-audit")).toHaveCount(0);
  });

  test("selecting a section via the workspace nav mounts only that section", async ({ page }) => {
    await mockEngineForValidation(page);
    await page.goto("/validation", { waitUntil: "domcontentloaded" });

    await page.getByTestId("validation-section-tab-wfe").click();
    await expect(page).toHaveURL(/[?&]section=wfe/);
    await expect(page.getByTestId("validation-section-wfe")).toBeVisible();
    await expect(page.getByTestId("validation-section-summary")).toHaveCount(0);
  });

  test("deep-linking directly to a section loads it without visiting summary first", async ({ page }) => {
    await mockEngineForValidation(page);
    await page.goto("/validation?section=reconciliation", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("validation-section-reconciliation")).toBeVisible();
    await expect(page.getByTestId("validation-section-summary")).toHaveCount(0);
  });

  test("browser back navigation restores the previous section", async ({ page }) => {
    await mockEngineForValidation(page);
    await page.goto("/validation", { waitUntil: "domcontentloaded" });

    await page.getByTestId("validation-section-tab-audit").click();
    await expect(page).toHaveURL(/[?&]section=audit/);
    await expect(page.getByTestId("validation-section-audit")).toBeVisible();

    await page.goBack();
    await expect(page.getByTestId("validation-section-summary")).toBeVisible();
    await expect(page.getByTestId("validation-section-audit")).toHaveCount(0);
  });

  test("an unrecognized section id falls back to summary instead of crashing", async ({ page }) => {
    await mockEngineForValidation(page);
    await page.goto("/validation?section=not-a-real-section", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("validation-section-summary")).toBeVisible();
    const body = (await page.textContent("body")) || "";
    expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
  });
});
