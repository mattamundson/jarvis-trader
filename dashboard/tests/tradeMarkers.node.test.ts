// Regression test for GT-10: /analysis price-chart trade markers were all
// rendering as "HOLD" (63/63 trades) because the marker-building code path
// read a nonexistent `action` field instead of the real `side` column on the
// GET /portfolio/history/trades response. Locks both the pure side-derivation
// helper and the marker builder to the real field name.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  deriveTradeSide,
  buildTradeMarkers,
  type TradeMarkerInput,
} from "../lib/tradeMarkers.ts";

test("deriveTradeSide reads the real `side` field, not a nonexistent `action`", () => {
  const buyTrade: TradeMarkerInput = { side: "buy" };
  const sellTrade: TradeMarkerInput = { side: "sell" };

  assert.equal(deriveTradeSide(buyTrade), "buy");
  assert.equal(deriveTradeSide(sellTrade), "sell");

  // The regression itself: a row with NO `side` (only the nonexistent
  // `action` field some earlier code path assumed existed) must fall back to
  // "hold" — it must never silently misreport as buy/sell either.
  assert.equal(
    deriveTradeSide({ action: "buy" } as unknown as TradeMarkerInput),
    "hold",
  );
});

test("buildTradeMarkers computes a buy entry marker (not hold) for a side='buy' fixture row", () => {
  const trades: TradeMarkerInput[] = [
    {
      symbol: "MES",
      side: "buy",
      entry_time: "2026-07-24T14:00:00Z",
      entry_price: 5000,
      exit_time: "2026-07-24T15:00:00Z",
      realized_pnl: 50,
    },
  ];

  const firstBarTime = Math.floor(new Date("2026-07-24T13:00:00Z").getTime() / 1000);
  const lastBarTime = Math.floor(new Date("2026-07-24T16:00:00Z").getTime() / 1000);

  const markers = buildTradeMarkers(trades, "MES", firstBarTime, lastBarTime);

  assert.equal(markers.length, 2, "expected one entry + one exit marker");
  const entryMarker = markers[0];

  // Real bug: this read `t.action` (undefined) and always fell back to
  // "hold", so shape/text/position all rendered as if every trade were flat.
  assert.match(entryMarker.text, /^BUY /, `marker text should start with BUY, got "${entryMarker.text}"`);
  assert.equal(entryMarker.shape, "arrowUp", "buy entries render as an up arrow");
  assert.equal(entryMarker.position, "belowBar", "buy entries render below the bar");
});

test("buildTradeMarkers computes a sell entry marker for a side='sell' fixture row", () => {
  const trades: TradeMarkerInput[] = [
    {
      symbol: "MES",
      side: "sell",
      entry_time: "2026-07-24T14:00:00Z",
      entry_price: 5000,
      exit_time: null,
      realized_pnl: null,
    },
  ];

  const firstBarTime = Math.floor(new Date("2026-07-24T13:00:00Z").getTime() / 1000);
  const lastBarTime = Math.floor(new Date("2026-07-24T16:00:00Z").getTime() / 1000);

  const markers = buildTradeMarkers(trades, "MES", firstBarTime, lastBarTime);

  assert.equal(markers.length, 1);
  assert.match(markers[0].text, /^SELL /);
  assert.equal(markers[0].shape, "arrowDown", "sell entries render as a down arrow");
});
