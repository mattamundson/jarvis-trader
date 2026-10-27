// Tests for ops page helper functions
import { describe, it } from "node:test";
import assert from "node:assert";
import {
  maskAccountId,
  formatNumber,
  calculateProofBarProgress,
  formatTimestamp,
  calculateAgeSeconds,
  formatDuration,
} from "../lib/opsHelpers.ts";

describe("opsHelpers", () => {
  describe("maskAccountId", () => {
    it("masks account ID to last 4 digits", () => {
      assert.strictEqual(maskAccountId("DUR375089"), "***5089");
      assert.strictEqual(maskAccountId("12345678"), "***5678");
    });

    it("returns short IDs unchanged", () => {
      assert.strictEqual(maskAccountId("1234"), "1234");
      assert.strictEqual(maskAccountId("123"), "123");
    });

    it("handles empty string", () => {
      assert.strictEqual(maskAccountId(""), "");
    });
  });

  describe("formatNumber", () => {
    it("formats numbers with 2 decimal places", () => {
      assert.strictEqual(formatNumber(1234.5), "1234.50");
      assert.strictEqual(formatNumber(0.1), "0.10");
      assert.strictEqual(formatNumber(100), "100.00");
    });

    it("handles negative numbers", () => {
      assert.strictEqual(formatNumber(-42.7), "-42.70");
    });
  });

  describe("calculateProofBarProgress", () => {
    it("calculates progress for sessions and setups", () => {
      assert.strictEqual(calculateProofBarProgress(0, 0), 0);
      assert.strictEqual(calculateProofBarProgress(5, 10), 50);
      assert.strictEqual(calculateProofBarProgress(10, 20), 100);
    });

    it("caps progress at 100%", () => {
      assert.strictEqual(calculateProofBarProgress(15, 30), 100);
      assert.strictEqual(calculateProofBarProgress(20, 40), 100);
    });

    it("handles partial progress", () => {
      assert.strictEqual(calculateProofBarProgress(7, 14), 70);
      assert.strictEqual(calculateProofBarProgress(3, 8), 35);
    });
  });

  describe("formatTimestamp", () => {
    it("formats ISO timestamp", () => {
      const timestamp = "2026-10-27T05:30:00Z";
      const formatted = formatTimestamp(timestamp);
      assert.ok(formatted.includes("Oct"));
      assert.ok(formatted.includes("27"));
    });

    it("handles invalid timestamp", () => {
      const invalid = "not-a-timestamp";
      assert.strictEqual(formatTimestamp(invalid), invalid);
    });
  });

  describe("calculateAgeSeconds", () => {
    it("calculates age from recent timestamp", () => {
      const now = new Date();
      const recent = new Date(now.getTime() - 5000);
      const age = calculateAgeSeconds(recent.toISOString());
      assert.ok(age >= 4 && age <= 6);
    });

    it("returns -1 for invalid timestamp", () => {
      assert.strictEqual(calculateAgeSeconds("invalid"), -1);
    });
  });

  describe("formatDuration", () => {
    it("formats seconds", () => {
      assert.strictEqual(formatDuration(0), "0s");
      assert.strictEqual(formatDuration(45), "45s");
      assert.strictEqual(formatDuration(59), "59s");
    });

    it("formats minutes and seconds", () => {
      assert.strictEqual(formatDuration(60), "1m 0s");
      assert.strictEqual(formatDuration(90), "1m 30s");
      assert.strictEqual(formatDuration(3599), "59m 59s");
    });

    it("formats hours and minutes", () => {
      assert.strictEqual(formatDuration(3600), "1h 0m");
      assert.strictEqual(formatDuration(7200), "2h 0m");
      assert.strictEqual(formatDuration(3660), "1h 1m");
    });

    it("handles unknown age", () => {
      assert.strictEqual(formatDuration(-1), "unknown");
    });
  });
});
