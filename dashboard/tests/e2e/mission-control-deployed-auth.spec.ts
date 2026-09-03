import { test, expect } from "@playwright/test";

test("LIVE deployed Mission Control and runtime snapshot are reachable with dashboard auth", async ({ page }) => {
  test.skip(
    !process.env.DASHBOARD_AUTH_USER || !process.env.DASHBOARD_AUTH_PASS,
    "dashboard auth credentials are not available in env",
  );

  await page.goto("/mission-control", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "MISSION CONTROL" })).toBeVisible();
  await expect(page.getByText("Runtime Snapshot")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/something went wrong/i);

  await page.goto("/api/runtime-snapshot", { waitUntil: "domcontentloaded" });
  const raw = (await page.textContent("body")) || "{}";
  const data = JSON.parse(raw);

  expect(data.available).toBe(true);
  expect(data.contract?.required_sections_present).toBe(true);
  expect(Array.isArray(data.contract?.missing_sections)).toBe(true);
  expect(typeof data.source_integrity?.overall).toBe("string");
  expect(Array.isArray(data.source_integrity?.checks)).toBe(true);
});
