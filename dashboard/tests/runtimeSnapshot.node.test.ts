import { test } from "node:test";
import assert from "node:assert/strict";
import {
  summarizeRuntimeSnapshot,
  type RawRuntimeSnapshot,
} from "../lib/runtimeSnapshot.ts";

test("missing snapshot -> unavailable, unknown freshness, load error preserved", () => {
  const out = summarizeRuntimeSnapshot(null, Date.parse("2026-09-02T12:00:00Z"), "missing_snapshot_file");
  assert.equal(out.available, false);
  assert.equal(out.freshness, "unknown");
  assert.equal(out.errors.load, "missing_snapshot_file");
  assert.equal(out.contract.required_sections_present, false);
  assert.match(out.findings.join("\n"), /missing or invalid/i);
  assert.match(out.findings.join("\n"), /Snapshot contract missing sections/i);
});

test("fresh snapshot summarizes engine-down, dashboard-up, split-brain eligibility truth", () => {
  const raw: RawRuntimeSnapshot = {
    artifact: "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
    schema_version: 1,
    captured_at_utc: "2026-09-02T11:30:00Z",
    repository: {
      branch: "feat/runtime-snapshot-cockpit",
      head: "abcdef1234567890abcdef1234567890abcdef12",
      status_porcelain_count: 5,
    },
    ports: {
      engine_8010_open: false,
      dashboard_3010_open: true,
      ib_paper_4002_open: false,
      ib_live_4001_open: false,
    },
    api: {
      health: {
        reachable: false,
        safe_health: {
          status: "unreachable",
          live_trading: false,
          paper_trading: true,
          kill_switch_active: true,
          ibkr_connected: false,
        },
      },
      backup_status: {
        reachable: true,
        safe_health: {
          healthy: true,
          backup_count: 7,
          last_backup_age_hours: 6,
        },
      },
      eligibility: {
        reachable: true,
        summary: {
          total: 4,
          tradeable: 1,
          enabled: 2,
          disagreements: 1,
        },
        symbols: [
          { symbol: "MES", enabled: true, tradeable: false, config_agrees: false },
          { symbol: "SPY", enabled: true, tradeable: true, config_agrees: true },
        ],
      },
    },
  };

  const out = summarizeRuntimeSnapshot(raw, Date.parse("2026-09-02T12:00:00Z"));
  assert.equal(out.available, true);
  assert.equal(out.freshness, "fresh");
  assert.equal(out.contract.schema_version, 1);
  assert.equal(out.contract.required_sections_present, true);
  assert.deepEqual(out.contract.missing_sections, []);
  assert.equal(out.repository.branch, "feat/runtime-snapshot-cockpit");
  assert.equal(out.repository.head_short, "abcdef123456");
  assert.equal(out.repository.dirty_count, 5);
  assert.equal(out.engine.reachable, false);
  assert.equal(out.engine.paper_trading, true);
  assert.equal(out.engine.kill_switch_active, true);
  assert.equal(out.ports.dashboard_3010_open, true);
  assert.deepEqual(out.eligibility.enabled_not_tradeable, ["MES"]);
  assert.deepEqual(out.eligibility.disagreeing_symbols, ["MES"]);
  assert.match(out.findings.join("\n"), /Engine HTTP health probe was unreachable/i);
  assert.match(out.findings.join("\n"), /Dashboard port 3010 was open/i);
  assert.match(out.findings.join("\n"), /Enabled but not tradeable symbols: MES/i);
});

test("stale snapshot and live-port exposure raise warning findings", () => {
  const raw: RawRuntimeSnapshot = {
    artifact: "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
    captured_at_utc: "2026-09-01T00:00:00Z",
    ports: {
      engine_8010_open: true,
      dashboard_3010_open: true,
      ib_paper_4002_open: true,
      ib_live_4001_open: true,
    },
    api: {
      health: {
        reachable: true,
        safe_health: {
          status: "ok",
          live_trading: true,
          paper_trading: false,
          kill_switch_active: false,
          ibkr_connected: true,
        },
      },
      backup_status: {
        reachable: false,
        safe_health: {
          healthy: false,
          backup_count: 0,
          last_backup_age_hours: 72,
        },
      },
      eligibility: {
        reachable: true,
        summary: {
          total: 1,
          tradeable: 1,
          enabled: 1,
          disagreements: 0,
        },
        symbols: [],
      },
    },
  };

  const out = summarizeRuntimeSnapshot(raw, Date.parse("2026-09-03T12:00:00Z"));
  assert.equal(out.freshness, "stale");
  assert.match(out.findings.join("\n"), /older than 24h/i);
  assert.match(out.findings.join("\n"), /IB live port 4001 was open/i);
  assert.match(out.findings.join("\n"), /live_trading=true/i);
  assert.match(out.findings.join("\n"), /Backup-status endpoint was unreachable/i);
  assert.match(out.findings.join("\n"), /Backup status was unhealthy/i);
});
