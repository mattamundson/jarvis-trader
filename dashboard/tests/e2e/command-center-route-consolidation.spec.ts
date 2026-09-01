import { test, expect } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";
import { installEngineMock, ERROR_BOUNDARY_TEXT } from "./_engineMock";

const DRILLDOWNS = [
  { path: "/mission-control", name: "MISSION CONTROL" },
  { path: "/today", name: "Today at a Glance" },
  { path: "/trust-pane", name: "Trust Pane" },
] as const;

async function installOfflineExternalMocks(page: import("@playwright/test").Page) {
  await page.route("**/api/amo/**", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "amo api unavailable in route-consolidation test" }),
    });
  });
  await page.route("**/api/master/**", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "master api unavailable in route-consolidation test" }),
    });
  });
  await page.route("**/api/fleet", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ agents: [], loops: [], generated_at: "2026-09-01T00:00:00.000Z" }),
    });
  });
}

test("command center is the canonical entry and exposes consolidation drilldowns", async ({ page }) => {
  await installCommandCenterFixture(page, "populated");

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
  const drilldowns = page.getByTestId("command-center-drilldowns");
  await expect(drilldowns.getByRole("link", { name: /Operations/i })).toHaveAttribute("href", "/command-center?view=operations");
  await expect(drilldowns.getByRole("link", { name: /Daily Brief/i })).toHaveAttribute("href", "/today");
  await expect(drilldowns.getByRole("link", { name: /Trust Audit/i })).toHaveAttribute("href", "/trust-pane");
});

test("sidebar keeps command center primary and demotes related routes to drilldowns", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installCommandCenterFixture(page, "populated");

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });

  const sidebar = page.locator("aside").first();
  await expect(sidebar.getByText("Command", { exact: true })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: /Command Center/i })).toHaveAttribute("href", "/command-center");
  await expect(sidebar.getByRole("link", { name: /Daily Brief/i })).toHaveAttribute("href", "/today");
  await expect(sidebar.getByRole("link", { name: /Operations/i })).toHaveAttribute("href", "/command-center?view=operations");
  await expect(sidebar.getByRole("link", { name: /Trust Audit/i })).toHaveAttribute("href", "/trust-pane");
  await expect(sidebar.getByRole("link", { name: /^Dashboard$/i })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: /Today at a Glance/i })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: /Mission Control/i })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: /Trust Pane/i })).toHaveCount(0);
});

test("command center operations query renders a real operations view state", async ({ page }) => {
  await installCommandCenterFixture(page, "populated");

  await page.goto("/command-center?view=operations", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
  const operationsView = page.getByTestId("command-center-operations-view");
  await expect(operationsView).toBeVisible();
  await expect(operationsView.getByRole("heading", { name: /Operations View/i })).toBeVisible();
  await expect(operationsView).toContainText(/Risk, execution, pipeline, diagnostics, and local fleet state/i);
});

for (const routeSpec of DRILLDOWNS) {
  test(`${routeSpec.path} remains reachable as a Command Center drilldown`, async ({ page }) => {
    await installEngineMock(page, "offline");
    await installOfflineExternalMocks(page);

    await page.goto(routeSpec.path, { waitUntil: "domcontentloaded" });

    await expect(page.getByText(routeSpec.name).first()).toBeVisible();
    await expect(page.locator("body")).not.toHaveText(ERROR_BOUNDARY_TEXT);
  });
}
