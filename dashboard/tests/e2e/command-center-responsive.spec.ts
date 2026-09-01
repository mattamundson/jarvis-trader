import { test, expect, type Locator, type Page } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";

type CriticalBox = {
  name: string;
  locator: Locator;
};

async function boxFor(item: CriticalBox) {
  const box = await item.locator.boundingBox();
  expect(box, `${item.name} must have a rendered bounding box`).not.toBeNull();
  return box!;
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() =>
    Math.max(
      0,
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
      document.body.scrollWidth - window.innerWidth,
    )
  );
  expect(overflow, "Command Center should not create horizontal viewport overflow").toBeLessThanOrEqual(2);
}

async function assertVerticalOrder(items: CriticalBox[]) {
  const boxes = [];
  for (const item of items) {
    boxes.push({ name: item.name, box: await boxFor(item) });
  }

  for (let index = 1; index < boxes.length; index += 1) {
    const previous = boxes[index - 1];
    const current = boxes[index];
    expect(
      current.box.y + 1,
      `${current.name} should not overlap above ${previous.name}`,
    ).toBeGreaterThanOrEqual(previous.box.y + previous.box.height);
  }
}

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

for (const viewport of VIEWPORTS) {
  test(`command-center responsive first viewport: ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await installCommandCenterFixture(page, "populated");

    await page.goto("/command-center", { waitUntil: "domcontentloaded" });

    const heading = page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i });
    const statusStrip = page.getByTestId("command-center-status-strip");
    const shell = page.getByTestId("canonical-shell");
    const drilldowns = page.getByTestId("command-center-drilldowns");
    const queue = page.getByTestId("command-center-trade-queue-panel");

    await expect(heading).toBeVisible();
    await expect(statusStrip).toBeVisible();
    await expect(shell).toBeVisible();
    await expect(drilldowns).toBeVisible();
    await expect(drilldowns.getByRole("link", { name: /Operations/i })).toHaveAttribute("href", "/mission-control");
    await expect(drilldowns.getByRole("link", { name: /Daily Brief/i })).toHaveAttribute("href", "/today");
    await expect(drilldowns.getByRole("link", { name: /Trust Audit/i })).toHaveAttribute("href", "/trust-pane");
    await expect(queue).toBeVisible();
    await expect(page.getByTestId("command-center-operations-summary")).toContainText(/Kill Switch\s*clear/i);
    await expect(page.getByTestId("command-center-operations-summary")).toContainText(/Order Rate\s*0\/10/i);
    await expect(page.getByTestId("command-center-operations-summary")).toContainText(/Broker Execution\s*no broker ack/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText("next gate: repair thesis");
    await expect(page.getByTestId("command-center-operations-grid")).toContainText("freshness: reported");
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/CACHE AGE\s*fresh/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/PROVIDER\s*unknown/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/BAR FRESHNESS\s*fresh/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/SOURCE PARITY\s*not wired/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/#749\s*pr\s*keep/i);
    await expect(page.getByTestId("command-center-operations-grid")).toContainText(/#754\s*pr\s*reference/i);
    await assertNoHorizontalOverflow(page);
    await assertVerticalOrder([
      { name: "heading", locator: heading },
      { name: "status strip", locator: statusStrip },
      { name: "canonical shell", locator: shell },
      { name: "trade queue", locator: queue },
    ]);

    const queueBox = await boxFor({ name: "trade queue", locator: queue });
    expect(queueBox.y, "trade queue should start in the first viewport").toBeLessThan(viewport.height);

    await test.info().attach(`command-center-${viewport.name}`, {
      body: await page.screenshot({ fullPage: false }),
      contentType: "image/png",
    });
  });
}
