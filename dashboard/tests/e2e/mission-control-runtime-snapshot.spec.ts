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
        contract: {
          artifact: "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
          schema_version: 1,
          required_sections_present: true,
          missing_sections: [],
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
        source_integrity: {
          overall: "fail",
          pass_count: 1,
          fail_count: 1,
          unknown_count: 0,
          failing_labels: ["Canonical deploy"],
          checks: [
            {
              label: "Active checkout",
              repo_root: "C:/Users/mattm/ThinkorSwim/jarvis-runtime-panel-master-20260902",
              status: "pass",
              finding_count: 0,
              required_path_failures: 0,
              git_metadata_failures: 0,
              workflow_action_failures: 0,
              findings: [],
            },
            {
              label: "Canonical deploy",
              repo_root: "C:/Users/mattm/ThinkorSwim/jarvis-trader",
              status: "fail",
              finding_count: 4,
              required_path_failures: 1,
              git_metadata_failures: 3,
              workflow_action_failures: 0,
              findings: [
                "required_path: AGENTS.md missing",
                "git_metadata: .git missing or unreadable",
              ],
            },
          ],
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

  await page.goto("/mission-control");

  await expect(page.getByRole("heading", { name: "MISSION CONTROL" })).toBeVisible();
  await expect(page.getByText("Runtime Snapshot")).toBeVisible();
  await expect(page.getByText("FRESH SNAPSHOT — 30m old")).toBeVisible();
  await expect(page.getByText("Runtime truth was captured recently enough to trust this panel at a glance.")).toBeVisible();
  await expect(page.getByText("ENGINE DOWN")).toBeVisible();
  await expect(page.getByText("feat/runtime-snapshot-cockpit")).toBeVisible();
  await expect(page.getByText("30m", { exact: true })).toBeVisible();
  await expect(page.getByText("24h", { exact: true })).toBeVisible();
  await expect(page.getByText("Enabled but not tradeable: MES")).toBeVisible();
  await expect(page.getByText("Kill switch was active at capture time.")).toBeVisible();
  await expect(page.getByText("Source integrity")).toBeVisible();
  await expect(page.getByText("Canonical deploy")).toBeVisible();
  await expect(page.getByText("required_path: AGENTS.md missing")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/something went wrong/i);
});

test("mission-control surfaces stale snapshot warnings prominently", async ({ page }) => {
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
        generated_at: "2026-09-01T00:00:00Z",
        age_seconds: 172800,
        freshness: "stale",
        repository: {
          branch: "feat/runtime-snapshot-cockpit",
          head_short: "abcdef123456",
          dirty_count: 0,
        },
        contract: {
          artifact: "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
          schema_version: 1,
          required_sections_present: true,
          missing_sections: [],
        },
        ports: {
          engine_8010_open: true,
          dashboard_3010_open: true,
          ib_paper_4002_open: true,
          ib_live_4001_open: false,
        },
        engine: {
          reachable: true,
          status: "ok",
          live_trading: false,
          paper_trading: true,
          kill_switch_active: false,
          ibkr_connected: true,
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
          disagreements: 0,
          enabled_not_tradeable: [],
          disagreeing_symbols: [],
        },
        source_integrity: {
          overall: "pass",
          pass_count: 1,
          fail_count: 0,
          unknown_count: 0,
          failing_labels: [],
          checks: [],
        },
        findings: ["Runtime snapshot is older than 24h."],
        errors: { load: null },
      },
    })
  );

  await page.goto("/mission-control");

  await expect(page.getByText("STALE SNAPSHOT — 2.0d old")).toBeVisible();
  await expect(page.getByText("Refresh the runtime truth artifact before trusting Mission Control state.")).toBeVisible();
  await expect(page.getByText("Captured")).toBeVisible();
  await expect(page.getByText("2d ago")).toBeVisible();
  await expect(page.getByText("2.0d", { exact: true })).toBeVisible();
});
