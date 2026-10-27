import { describe, it } from "node:test";
import * as assert from "node:assert/strict";
import {
  computeSetupStats,
  groupBySetupType,
  groupByTimeOfDay,
  SAMPLE_SETUPS,
  type SetupRecord,
} from "@/lib/setupScorecard";

describe("setupScorecard", () => {
  describe("computeSetupStats", () => {
    it("returns zero stats for empty array", () => {
      const stats = computeSetupStats([]);
      assert.equal(stats.total, 0);
      assert.equal(stats.wins, 0);
      assert.equal(stats.losses, 0);
      assert.equal(stats.hit_rate, 0);
      assert.equal(stats.avg_r, 0);
    });

    it("computes correct stats for sample data", () => {
      const stats = computeSetupStats(SAMPLE_SETUPS);
      assert.equal(stats.total, 8);
      assert.equal(stats.wins, 5);
      assert.equal(stats.losses, 3);
      assert.equal(stats.hit_rate, 62.5);
    });

    it("computes correct average R", () => {
      const records: SetupRecord[] = [
        {
          date: "2026-10-01",
          setup_type: "test",
          direction: "long",
          entry: 100,
          stop: 90,
          targets: [110],
          exit: 110,
          outcome: "win",
          r: 1.0,
          mfe: 1.2,
          mae: -0.1,
        },
        {
          date: "2026-10-02",
          setup_type: "test",
          direction: "long",
          entry: 100,
          stop: 90,
          targets: [110],
          exit: 90,
          outcome: "loss",
          r: -1.0,
          mfe: 0.2,
          mae: -1.0,
        },
      ];
      const stats = computeSetupStats(records);
      assert.equal(stats.avg_r, 0);
      assert.equal(stats.expectancy, 0);
    });

    it("identifies best and worst R", () => {
      const stats = computeSetupStats(SAMPLE_SETUPS);
      assert.ok(stats.best_r > 0);
      assert.ok(stats.worst_r < 0);
    });

    it("computes MFE and MAE averages", () => {
      const stats = computeSetupStats(SAMPLE_SETUPS);
      assert.ok(stats.avg_mfe > 0);
      assert.ok(stats.avg_mae < 0);
    });
  });

  describe("groupBySetupType", () => {
    it("groups records by setup type", () => {
      const groups = groupBySetupType(SAMPLE_SETUPS);
      assert.ok(groups.size > 0);
      assert.ok(groups.has("breakout"));
      assert.ok(groups.has("pullback"));
      assert.ok(groups.has("reversal"));
    });

    it("returns correct count per group", () => {
      const groups = groupBySetupType(SAMPLE_SETUPS);
      const breakoutCount = groups.get("breakout")?.length ?? 0;
      assert.ok(breakoutCount > 0);
    });

    it("handles empty array", () => {
      const groups = groupBySetupType([]);
      assert.equal(groups.size, 0);
    });
  });

  describe("groupByTimeOfDay", () => {
    it("groups records by time of day", () => {
      const groups = groupByTimeOfDay(SAMPLE_SETUPS);
      assert.ok(groups.size > 0);
    });

    it("handles missing time_of_day field", () => {
      const records: SetupRecord[] = [
        {
          date: "2026-10-01",
          setup_type: "test",
          direction: "long",
          entry: 100,
          stop: 90,
          targets: [110],
          exit: 110,
          outcome: "win",
          r: 1.0,
          mfe: 1.2,
          mae: -0.1,
        },
      ];
      const groups = groupByTimeOfDay(records);
      assert.ok(groups.has("unknown"));
    });

    it("returns correct count per time slot", () => {
      const groups = groupByTimeOfDay(SAMPLE_SETUPS);
      let totalCount = 0;
      for (const records of groups.values()) {
        totalCount += records.length;
      }
      assert.equal(totalCount, SAMPLE_SETUPS.length);
    });
  });

  describe("SAMPLE_SETUPS fixture", () => {
    it("contains valid data", () => {
      assert.ok(SAMPLE_SETUPS.length > 0);
      for (const setup of SAMPLE_SETUPS) {
        assert.ok(setup.date);
        assert.ok(setup.setup_type);
        assert.ok(setup.direction === "long" || setup.direction === "short");
        assert.ok(typeof setup.entry === "number");
        assert.ok(typeof setup.stop === "number");
        assert.ok(Array.isArray(setup.targets));
        assert.ok(typeof setup.exit === "number");
        assert.ok(["win", "loss", "breakeven"].includes(setup.outcome));
        assert.ok(typeof setup.r === "number");
        assert.ok(typeof setup.mfe === "number");
        assert.ok(typeof setup.mae === "number");
      }
    });

    it("R values match outcome", () => {
      for (const setup of SAMPLE_SETUPS) {
        if (setup.outcome === "win") {
          assert.ok(setup.r > 0, `win setup should have positive R, got ${setup.r}`);
        } else if (setup.outcome === "loss") {
          assert.ok(setup.r < 0, `loss setup should have negative R, got ${setup.r}`);
        }
      }
    });
  });
});
