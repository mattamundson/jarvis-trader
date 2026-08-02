// Tier 1 (honesty/provenance) component tests — Phase 9.2, P9-2.
//
// `classifyProvenance` (lib/provenance.ts) is the single gate every honesty
// badge renders through: it decides whether a value is shown as LIVE, STALE,
// STATIC, or NO DATA. These tests pin down its two most safety-critical
// contracts:
//   1. A live-tier envelope that has aged past `stale_after_s` must render
//      STALE, never keep flashing LIVE just because the server once said
//      `is_live: true`.
//   2. Passing `nowMs: null` (SSR / first render, no clock yet) must not
//      throw — it should honor the server's verdict without attempting an
//      age computation.
import { describe, expect, it } from "vitest";
import { classifyProvenance, type DataEnvelope } from "@/lib/provenance";

function makeEnvelope(overrides: Partial<DataEnvelope> = {}): DataEnvelope {
  return {
    value: 100,
    source: "ibkr",
    as_of: 1_000, // epoch seconds
    is_live: true,
    stale_after_s: 30,
    ...overrides,
  };
}

describe("classifyProvenance", () => {
  it("renders STALE, never LIVE, once a live-tier envelope ages past stale_after_s", () => {
    const env = makeEnvelope({ as_of: 1_000, stale_after_s: 30, is_live: true });
    const nowMs = (1_000 + 31) * 1000; // 31s later — 1s past the 30s window
    const view = classifyProvenance(env, nowMs);

    expect(view.status).toBe("stale");
    expect(view.label).toBe("STALE");
    expect(view.isLive).toBe(false);
    expect(view.badgeVariant).toBe("static");
  });

  it("classifies as LIVE when the value is well within its freshness window", () => {
    const env = makeEnvelope({ as_of: 1_000, stale_after_s: 30, is_live: true });
    const nowMs = (1_000 + 5) * 1000; // 5s later, within the 30s window
    const view = classifyProvenance(env, nowMs);

    expect(view.status).toBe("live");
    expect(view.label).toBe("LIVE");
    expect(view.isLive).toBe(true);
    expect(view.badgeVariant).toBe("live");
  });

  it("does not throw when nowMs is null, and honors the server verdict without a clock", () => {
    const env = makeEnvelope({ is_live: true });

    expect(() => classifyProvenance(env, null)).not.toThrow();

    const view = classifyProvenance(env, null);
    expect(view.ageSeconds).toBeNull();
    expect(view.status).toBe("live");
  });

  it("does not throw when nowMs is null and the server already downgraded the value", () => {
    const env = makeEnvelope({ is_live: false });

    expect(() => classifyProvenance(env, null)).not.toThrow();

    const view = classifyProvenance(env, null);
    expect(view.status).toBe("stale");
    expect(view.isLive).toBe(false);
  });

  it("never classifies a non-live-tier source as LIVE, regardless of is_live", () => {
    const env = makeEnvelope({ source: "cached_snapshot", is_live: true });
    const view = classifyProvenance(env, Date.now());

    expect(view.status).toBe("static");
    expect(view.isLive).toBe(false);
  });

  it("classifies a null/undefined envelope value as unavailable (NO DATA)", () => {
    const view = classifyProvenance(null, Date.now());

    expect(view.status).toBe("unavailable");
    expect(view.label).toBe("NO DATA");
    expect(view.isLive).toBe(false);
  });

  it("does not throw for a null envelope with nowMs also null", () => {
    expect(() => classifyProvenance(null, null)).not.toThrow();
    expect(classifyProvenance(undefined, null).status).toBe("unavailable");
  });
});
