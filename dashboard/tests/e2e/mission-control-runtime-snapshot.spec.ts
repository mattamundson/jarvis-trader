import { test, expect } from "@playwright/test";

test("mission-control renders runtime snapshot findings even when engine routes are unreachable", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 503, json: { detail: "engine down" } }));

  await page.route("**/api/fleet", (route) =>
    route.fulfill({
      status: 200,
      json: {
        canary: { overall: "GREEN", failing: [], generated_at: null },
        counts: { total: 1, green: 1, red: 0, stale: 0 },
        red_loops: [],
        stale_loops: [],
        loops: [{ id: "jarvis-dashboard-crash-watch", status: "ok", runner: "cron", schedule: "HOURLY", last_heartbeat: null, color: "GREEN", stale: false }],
        errors: { registry: null, canary: null },
      },
    })
  );

  await page.route("**/api/runtime-snapshot", (route) =>
    route.fulfill({
      status: 200,
      json: {
        available: true,
        source: "phase0_runtime_truth_snapshot",
        generated_at: "2026-09-02T11:30:00Z",
        age_seconds: 1800,
        freshness: "fresh",
        repository: {
          branch: "feat/runtime-snapshot-cockpit",
          head_short: "abcdef123456",
          dirty_count: 5,
        },
        ports: {
          engine_8010_open: false,
          dashboard_3010_open: true,
          ib_paper_4002_open: false,
          ib_live_4001_open: false,
        },
        engine: {
          reachable: false,
          status: "unreachable",
          live_trading: false,
          paper_trading: true,
          kill_switch_active: true,
          ibkr_connected: false,
        },
        backup: {
          reachable: true,
          healthy: true,
          backup_count: 7,
          last_backup_age_hours: 6,
        },
        eligibility: {
          reachable: true,
          total: 4,
          tradeable: 1,
          enabled: 2,
          disagreements: 1,
          enabled_not_tradeable: ["MES"],
          disagreeing_symbols: ["MES"],
        },
        findings: [
          "Engine HTTP health probe was unreachable at capture time.",
          "Dashboard port 3010 was open at capture time.",
          "Kill switch was active at capture time.",
          "Enabled but not tradeable symbols: MES.",
        ],
        errors: { load: null },
      },
    })
  );

  await page.goto("/mission-control", { waitUntil: "networkidle" });

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("MISSION CONTROL");
  expect(body).toContain("Runtime Snapshot");
  expect(body).toContain("ENGINE DOWN");
  expect(body).toContain("feat/runtime-snapshot-cockpit");
  expect(body).toContain("Enabled but not tradeable: MES");
  expect(body).toContain("Kill switch was active at capture time.");
  expect(body).not.toMatch(/something went wrong/i);
});
