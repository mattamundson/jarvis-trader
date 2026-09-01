import { test, expect } from "@playwright/test";

const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

test("command-center smoke: renders flagship header under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: { MES: { symbol: "MES", ...NULL_PRICE }, MGC: { symbol: "MGC", ...NULL_PRICE } },
      });
    }
    if (u.includes("/decisions/recent") || u.includes("/portfolio/history/trades")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (u.includes("/scheduler/status")) {
      return route.fulfill({ status: 200, json: { jobs: [] } });
    }
    if (u.includes("/journal/review/stats")) {
      return route.fulfill({
        status: 200,
        json: {
          total_trades: 0,
          win_rate: 0,
          avg_win_usd: 0,
          avg_loss_usd: 0,
          risk_reward_ratio: 0,
          expected_value_usd: 0,
          trades_per_week: 0,
          diagnosis: "insufficient_data",
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /KILL SWITCH/i })).toBeVisible();
  const shell = page.getByTestId("canonical-shell");
  await expect(shell.getByText("CANONICAL SHELL")).toBeVisible();
  await expect(shell.getByRole("link", { name: /SYSTEM STATUS/i })).toBeVisible();
  await expect(shell.getByRole("link", { name: /TRADE QUEUE/i })).toBeVisible();
  await expect(shell.getByRole("link", { name: /ELIGIBILITY/i })).toBeVisible();
  await expect(shell.getByRole("link", { name: /STRATEGY LEDGER/i })).toBeVisible();
  await expect(shell.getByRole("link", { name: /DATA INTEGRITY/i })).toBeVisible();
  await expect(shell.getByRole("link", { name: /RESEARCH INTAKE/i })).toBeVisible();
  const strip = page.getByTestId("command-center-status-strip");
  await expect(strip.getByText("ENGINE", { exact: true })).toBeVisible();
  await expect(strip.getByText("BROKER", { exact: true })).toBeVisible();
  await expect(strip.getByText("SAFETY", { exact: true })).toBeVisible();
  await expect(strip.getByText("DATA", { exact: true })).toBeVisible();
});
