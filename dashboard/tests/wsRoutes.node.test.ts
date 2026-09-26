import assert from "node:assert/strict";
import { test } from "node:test";

import { isPublicReadOnlyPath, isWebSocketPath, isWebSocketUpgrade } from "@/lib/publicRoutes";

test("only the two documented read-only paths are public", () => {
  assert.equal(isPublicReadOnlyPath("/market-brief-public"), true);
  assert.equal(isPublicReadOnlyPath("/api/public-market-brief/latest"), true);
  // control surfaces must never be public
  for (const p of ["/mission-control", "/api/engine/health", "/api/market-brief", "/", "/ws/events"]) {
    assert.equal(isPublicReadOnlyPath(p), false, `${p} must not be public`);
  }
});

test("/ws paths are recognised so they cannot be silently excluded by prefix", () => {
  assert.equal(isWebSocketPath("/ws"), true);
  assert.equal(isWebSocketPath("/ws/events"), true);
  assert.equal(isWebSocketPath("/ws/pipeline"), true);
  assert.equal(isWebSocketPath("/ws/anything-not-a-route"), true, "whole prefix, not a route list");
  // must not match lookalikes
  assert.equal(isWebSocketPath("/wsomething"), false);
  assert.equal(isWebSocketPath("/market-brief-public"), false);
});

test("only a genuine websocket handshake bypasses auth", () => {
  assert.equal(isWebSocketUpgrade("websocket"), true);
  assert.equal(isWebSocketUpgrade("WebSocket"), true, "case-insensitive");
  assert.equal(isWebSocketUpgrade("  websocket  "), true, "trimmed");
});

test("ordinary requests do NOT count as an upgrade (the auth-bypass regression)", () => {
  // A plain GET under /ws/ previously skipped Basic Auth entirely and reached the engine
  // tunnel. None of these may be treated as an upgrade.
  assert.equal(isWebSocketUpgrade(null), false);
  assert.equal(isWebSocketUpgrade(""), false);
  assert.equal(isWebSocketUpgrade("h2c"), false);
  assert.equal(isWebSocketUpgrade("keep-alive"), false);
  assert.equal(isWebSocketUpgrade("websocket-fake"), false, "must be an exact token match");
  assert.equal(isWebSocketUpgrade("websocket, h2c"), false, "ambiguous multi-value is not trusted");
});
