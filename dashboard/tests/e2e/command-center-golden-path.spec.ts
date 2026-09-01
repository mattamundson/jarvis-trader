import { test, expect } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";

// P5.2: flagship (/command-center, per P2.1's `/` -> `/command-center` dissolve)
// golden path under degraded engine data, plus a security assertion that the
// server-only ENGINE_API_KEY (injected by app/api/engine/[...path]/route.ts)
// never reaches the browser -- no request header, no page source leak.

test("flagship /command-center survives degraded engine data without white-screening", async ({ page }) => {
  await installCommandCenterFixture(page, "degraded");

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });
  const body = (await page.textContent("body")) || "";

  expect(body, "flagship header did not render").toContain("COMMAND CENTER");
  expect(body, "canonical shell map did not render").toContain("CANONICAL SHELL");
  expect(body, "trade queue shell region did not render").toContain("TRADE QUEUE");
  expect(body, "eligibility shell region did not render").toContain("ELIGIBILITY");
  expect(body, "strategy ledger shell region did not render").toContain("STRATEGY LEDGER");
  expect(body, "data integrity shell region did not render").toContain("DATA INTEGRITY");
  expect(body, "research intake shell region did not render").toContain("RESEARCH INTAKE");
  expect(body, "independent status strip did not render").toContain("ENGINE");
  expect(body, "broker status chip did not render").toContain("BROKER");
  expect(body, "safety status chip did not render").toContain("SAFETY");
  expect(body, "data status chip did not render").toContain("DATA");
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
});

test("no engine API key reaches the browser (request headers or page source)", async ({ page }) => {
  const leakedHeaderRequests: string[] = [];
  page.on("request", (request) => {
    const headers = request.headers();
    if (Object.keys(headers).some((h) => h.toLowerCase() === "x-api-key")) {
      leakedHeaderRequests.push(request.url());
    }
  });

  await installCommandCenterFixture(page, "degraded");

  await page.goto("/command-center", { waitUntil: "networkidle" });

  expect(leakedHeaderRequests, "a browser-originated request carried an X-API-Key header").toEqual([]);

  // The server injects the key server-side only (lib/api.ts:8-10 / the proxy
  // route) -- it must never be inlined into SSR HTML or the client bundle.
  const html = await page.content();
  expect(html, "ENGINE_API_KEY env var name leaked into page source").not.toContain("ENGINE_API_KEY");
  expect(html, "the documented dev-placeholder engine key leaked into page source").not.toContain(
    "jarvis-dev-key-change-me"
  );
});
