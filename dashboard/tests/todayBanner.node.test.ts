// GT-09 regression: /today status banner must distinguish "degraded but
// connected" (e.g. a single LLM provider leg down while the engine, IBKR,
// and market data are all fine) from genuinely unreachable (fetch/network
// failure, or no broker/data connection at all). Before the fix,
// getBannerVariant collapsed EVERY health.status !== 'ok' into the alarming
// "ENGINE UNREACHABLE" banner regardless of connectivity.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { getBannerVariant, type BannerHealthInput } from "../lib/todayBanner.ts";

function health(overrides: Partial<BannerHealthInput> = {}): BannerHealthInput {
  return {
    status: "ok",
    live_trading: false,
    ibkr_connected: true,
    schwab_connected: false,
    ibkr_data_connected: true,
    tradingview_mcp_healthy: true,
    ...overrides,
  };
}

test("degraded status but connected broker + fresh market data -> NOT unreachable", () => {
  const h = health({
    status: "degraded", // e.g. single LLM provider leg down
    ibkr_connected: true,
    ibkr_data_connected: true,
  });
  const variant = getBannerVariant(h, false);
  assert.notEqual(variant, "unreachable");
  assert.equal(variant, "degraded");
});

test("degraded status, IBKR down but TradingView MCP still fresh -> degraded, not unreachable", () => {
  const h = health({
    status: "degraded",
    ibkr_connected: false,
    schwab_connected: false,
    ibkr_data_connected: false,
    tradingview_mcp_healthy: true,
  });
  assert.equal(getBannerVariant(h, false), "degraded");
});

test("fetch/network failure (isError) -> unreachable regardless of health payload", () => {
  assert.equal(getBannerVariant(undefined, true), "unreachable");
  assert.equal(getBannerVariant(health({ status: "ok" }), true), "unreachable");
});

test("no health response at all -> unreachable", () => {
  assert.equal(getBannerVariant(undefined, false), "unreachable");
});

test("degraded status with no broker connection and no fresh data feed -> genuinely unreachable", () => {
  const h = health({
    status: "degraded",
    ibkr_connected: false,
    schwab_connected: false,
    ibkr_data_connected: false,
    tradingview_mcp_healthy: false,
  });
  assert.equal(getBannerVariant(h, false), "unreachable");
});

test("status ok, live_trading true -> live_ok", () => {
  const h = health({ status: "ok", live_trading: true });
  assert.equal(getBannerVariant(h, false), "live_ok");
});

test("status ok, live_trading false -> paper_ok", () => {
  const h = health({ status: "ok", live_trading: false });
  assert.equal(getBannerVariant(h, false), "paper_ok");
});

test("status ok but neither broker connected -> degraded (execution/data leg down)", () => {
  const h = health({
    status: "ok",
    ibkr_connected: false,
    schwab_connected: false,
  });
  assert.equal(getBannerVariant(h, false), "degraded");
});

test("schwab connected (not ibkr) counts as a connected broker", () => {
  const h = health({
    status: "degraded",
    ibkr_connected: false,
    schwab_connected: true,
    ibkr_data_connected: false,
    tradingview_mcp_healthy: false,
  });
  assert.equal(getBannerVariant(h, false), "degraded");
});
