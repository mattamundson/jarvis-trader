// Tests for Hermes gates.json adapter
import { describe, it } from "node:test";
import assert from "node:assert";
import { adaptHermesToOps, verifyNoMoneyInOutput } from "../lib/hermesAdapter.ts";
import type { HermesGatesData } from "../lib/hermesTypes.ts";

describe("hermesAdapter", () => {
  const sampleHermes: HermesGatesData = {
    pulled_ct: "2026-10-27T05:30:00Z",
    source: "hermes-gates",
    E: 1234.56,
    R: 2.1,
    live_size: 1000,
    live_legal: true,
    go_live: {
      clean_sessions: { have: 7, need: 10, met: false },
      scored_setups: { have: 14, need: 20, avg_R: 1.8, met: false },
      rule_breaks_30d: { confirmed: 0, method_note: "none", pending: 0, met: true },
    },
    options_1R: { clean: 5, of: 10, no_strikes_30d: true, met: false },
    lockouts: [
      { name: "test-lockout", through: "2026-11-01", active: false, note: "Resolved" },
    ],
    e1: { counts_toward_20: true, flag: null, stop: null },
    e1_log: [
      { date: "2026-10-27", call: "long", points: 5890.25, ref_R: 2.1, graded_ct: 3 },
      { date: "2026-10-27", call: "short", points: 5885.5, ref_R: -0.5, graded_ct: 1 },
    ],
    strikes: [
      { date: "2026-10-20", bans: "Late entry", status: "pending", method_note: "Manual review pending" },
    ],
  };

  describe("adaptHermesToOps", () => {
    it("maps proof_bar fields correctly", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.proof_bar.clean_paper_sessions, 7);
      assert.strictEqual(result.proof_bar.scored_setups, 14);
      assert.strictEqual(result.proof_bar.avg_r, 1.8);
      assert.strictEqual(result.proof_bar.rule_breaks, 0);
    });

    it("does not map pulled_ct to tick_recorder_last_write", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.system_health.tick_recorder_last_write, null);
    });

    it("does not map live_legal to ib_gateway_status", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.system_health.ib_gateway_status, "unknown");
      assert.strictEqual(result.system_health.live_legal, true);
    });

    it("shows live_legal as separate field", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.system_health.live_legal, true);
      
      const hermesNotLegal = { ...sampleHermes, live_legal: false };
      const resultNotLegal = adaptHermesToOps(hermesNotLegal);
      assert.strictEqual(resultNotLegal.system_health.live_legal, false);
    });

    it("maps strikes array with method_note", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.strikes.length, 1);
      assert.strictEqual(result.strikes[0].date, "2026-10-20");
      assert.strictEqual(result.strikes[0].reason, "Late entry");
      assert.strictEqual(result.strikes[0].severity, "minor");
      assert.strictEqual(result.strikes[0].method_note, "Manual review pending");
    });

    it("preserves sessions_met value exactly from gates.json", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.proof_bar.sessions_met, false);
    });

    it("shows met only when sessions_met === true", () => {
      const hermesMet: HermesGatesData = {
        ...sampleHermes,
        go_live: {
          ...sampleHermes.go_live,
          clean_sessions: { have: 12, need: 10, met: true },
        },
      };
      const result = adaptHermesToOps(hermesMet);
      assert.strictEqual(result.proof_bar.sessions_met, true);
    });

    it("handles met='pending' string value", () => {
      const hermesPending: HermesGatesData = {
        ...sampleHermes,
        go_live: {
          ...sampleHermes.go_live,
          clean_sessions: { have: 12, need: 10, met: "pending" },
        },
      };
      const result = adaptHermesToOps(hermesPending);
      assert.strictEqual(result.proof_bar.sessions_met, "pending");
      assert.notStrictEqual(result.proof_bar.sessions_met, true);
    });

    it("maps lockout status", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.lockouts.length, 1);
      assert.strictEqual(result.lockouts[0].active, false);
    });

    it("maps e1_log to journal with pre-holdout note", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.today_journal.length, 2);
      assert.strictEqual(result.today_journal[0].symbol, "MES");
      assert.strictEqual(result.today_journal[0].direction, "long");
    });

    it("does not include pre-holdout note when counts_toward_20 is true", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.ok(result.today_journal[0].notes.includes("Holdout"));
      assert.ok(!result.today_journal[0].notes.includes("Pre-holdout"));
    });

    it("preserves met fields for all go-live gates", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.proof_bar.sessions_met, false);
      assert.strictEqual(result.proof_bar.setups_met, false);
      assert.strictEqual(result.proof_bar.avg_r_met, true);
      assert.strictEqual(result.proof_bar.rule_breaks_met, true);
    });

    it("supports multiple active lockouts", () => {
      const hermesMulti: HermesGatesData = {
        ...sampleHermes,
        lockouts: [
          { name: "lockout-1", through: "2026-11-01", active: true, note: "First" },
          { name: "lockout-2", since: "2026-10-25", active: true, note: "Second" },
          { name: "lockout-3", through: "2026-10-20", active: false, note: "Past" },
        ],
      };
      const result = adaptHermesToOps(hermesMulti);
      assert.strictEqual(result.lockouts.length, 3);
      assert.strictEqual(result.lockouts.filter((l) => l.active).length, 2);
    });

    it("adds status field to strikes", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(result.strikes[0].status, "pending");
      assert.strictEqual(result.strikes[0].method_note, "Manual review pending");
    });

    it("handles missing optional fields", () => {
      const hermesMinimal: HermesGatesData = {
        ...sampleHermes,
        e1_log: undefined,
        strikes: undefined,
      };
      const result = adaptHermesToOps(hermesMinimal);
      assert.strictEqual(result.today_journal.length, 0);
      assert.strictEqual(result.strikes.length, 0);
    });
  });

  describe("verifyNoMoneyInOutput", () => {
    it("returns true when output contains no E field or dollar signs", () => {
      const result = adaptHermesToOps(sampleHermes);
      assert.strictEqual(verifyNoMoneyInOutput(result), true);
    });

    it("detects E field in output", () => {
      const result = adaptHermesToOps(sampleHermes);
      const contaminated = { ...result, E: 1234 };
      assert.strictEqual(verifyNoMoneyInOutput(contaminated as any), false);
    });

    it("never includes E field from source", () => {
      const result = adaptHermesToOps(sampleHermes);
      const serialized = JSON.stringify(result);
      assert.ok(!serialized.includes('"E"'));
      assert.ok(!serialized.includes("1234.56"));
    });
  });
});
