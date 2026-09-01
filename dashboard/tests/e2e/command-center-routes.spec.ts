import { test, expect } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";

const COMMAND_CENTER_ROUTES = ["/", "/dashboard", "/command-center"] as const;

for (const routePath of COMMAND_CENTER_ROUTES) {
  test(`${routePath} resolves to Command Center with shared fixture contracts`, async ({ page }) => {
    await installCommandCenterFixture(page, "empty");

    await page.goto(routePath, { waitUntil: "domcontentloaded" });
    if (routePath !== "/command-center") {
      await page.waitForURL("**/command-center", { waitUntil: "domcontentloaded" });
    }

    await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
    await expect(page.getByTestId("canonical-shell")).toBeVisible();
    await expect(page.getByTestId("command-center-status-strip")).toBeVisible();
    await expect(page.getByTestId("command-center-trade-queue-panel")).toContainText("ORDER ACTIONS DISABLED");
  });
}
