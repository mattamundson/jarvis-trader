import { test, expect } from "@playwright/test";

test("data-integrity page renders expanded backend contract states", async ({ page }) => {
  await page.route("**/api/engine/system/data-integrity", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        timestamp: "2026-09-01T15:00:00.000Z",
        status: "degraded",
        stale_after_seconds: 900,
        count: 1,
        sources: [
          {
            source: "ticks:MES1!",
            kind: "market_data",
            provider: null,
            provider_tier: null,
            last_update: "2026-09-01T15:00:00.000Z",
            latency_sec: 0.5,
            age_seconds: 0.5,
            status: "healthy",
            cache_key: "datasource:ticks:MES1!:last_update",
          },
        ],
        cache_age: { status: "fresh", max_age_seconds: 0.5, stale_after_seconds: 900, by_source: [] },
        provider_tier: {
          status: "unknown",
          active: null,
          primary: null,
          fallbacks: [],
          reason: "provider metadata not wired",
        },
        bar_freshness: {
          status: "fresh",
          stale_after_seconds: 900,
          max_lag_seconds: 0.5,
          symbols: ["MES1!"],
          timeframes: [],
          stale_symbols: [],
          unknown_symbols: [],
        },
        source_parity: {
          status: "not_wired",
          window_seconds: null,
          checked_symbols: [],
          reference_source: null,
          compared_sources: [],
          max_delta_bps: null,
          mismatches: [],
          missing_sources: [],
        },
        trade_enablement: {
          status: "blocked",
          blocking_reasons: ["provider_tier_unknown", "source_parity_not_wired"],
        },
      }),
    });
  });

  await page.goto("/data-integrity", { waitUntil: "domcontentloaded" });

  const body = page.locator("body");
  await expect(page.getByRole("heading", { name: "Data Integrity" })).toBeVisible();
  await expect(body).toContainText(/Cache Age\s*fresh/i);
  await expect(body).toContainText(/Provider Tier\s*unknown/i);
  await expect(body).toContainText(/Bar Freshness\s*fresh/i);
  await expect(body).toContainText(/Source Parity\s*not wired/i);
  await expect(body).toContainText(/Trade Enablement\s*blocked/i);
  await expect(body).toContainText("ticks:MES1!");
});
