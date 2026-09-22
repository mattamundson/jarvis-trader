import { test, expect } from "@playwright/test";

test("public market brief page is reachable without dashboard chrome", async ({ page, request }) => {
  const api = await request.get("/api/public-market-brief/latest");
  expect(api.status()).toBe(200);
  const payload = await api.json();
  expect(payload.mode).toBe("ANALYSIS_ONLY");
  expect(payload.orders_enabled).toBe(false);
  expect(payload.risk_config_touched).toBe(false);
  expect(payload.publicContract.tradingControlsExposed).toBe(false);
  expect(payload.publicContract.localPathExposed).toBe(false);
  expect(JSON.stringify(payload)).not.toContain("C:/Users");

  await page.goto("/market-brief-public");
  await expect(page.getByRole("heading", { name: "JARVIS Market Brief" })).toBeVisible();
  await expect(page.getByText("ANALYSIS ONLY")).toBeVisible();
  await expect(page.getByText("BASE RATE", { exact: true })).toBeVisible();
  await expect(page.getByText("Conditional diagnostic")).toBeVisible();
  await expect(page.getByText("NO MEASURED EDGE")).toBeVisible();
  await expect(page.getByText("Public contract:")).toBeVisible();

  // Public shell must not expose the normal dashboard navigation/control surface.
  await expect(page.getByText("MISSION CONTROL", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Command Center", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Pending Approvals", { exact: true })).toHaveCount(0);
});
