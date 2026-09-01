import { test, expect } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";

test("command-center smoke: renders flagship header under mocked engine", async ({ page }) => {
  await installCommandCenterFixture(page, "empty");

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
  const queue = page.getByTestId("command-center-trade-queue-panel");
  await expect(queue).toBeVisible();
  await expect(queue.getByText("ORDER ACTIONS DISABLED")).toBeVisible();
  await expect(queue.getByText("DECISIONS", { exact: true })).toBeVisible();
  await expect(queue.getByText("POSITIONS", { exact: true })).toBeVisible();
  await expect(queue.getByText("STOP REVIEW", { exact: true })).toBeVisible();
  await expect(queue.getByText("JOURNAL", { exact: true })).toBeVisible();
  const operations = page.getByTestId("command-center-operations-grid");
  await expect(operations.getByText("ELIGIBILITY PANEL")).toBeVisible();
  await expect(operations.getByText("STRATEGY LEDGER PANEL")).toBeVisible();
  await expect(operations.getByText("DATA INTEGRITY PANEL")).toBeVisible();
  await expect(operations.getByText("RESEARCH INTAKE PANEL")).toBeVisible();
  await expect(operations.getByText("SOURCE PARITY")).toBeVisible();
  await expect(operations.getByText(/research-only/i).first()).toBeVisible();
});
