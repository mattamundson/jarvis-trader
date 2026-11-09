import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  buildDrawdownProjection,
  equityPeakDisclaimer,
  haltGapSentence,
  haltPeakAuditSentence,
  peakWindowNote,
  projectionCardState,
  PROJECTION_LOADING_COPY,
  PROJECTION_UNAVAILABLE_COPY,
  symbolSplitSentence,
  type ClosedTradeRow,
  type EquityCurvePoint,
} from "../lib/drawdownProjection.ts";

const EQUITY = 14426.5661;
const FRACTION = 0.0641630158607052;
const HALT = 0.2;
const AVG_LOSS = 101.7731;
const PEAK = 15415.6828;

test("live safety inputs use the halt peak, not closed-trade max drawdown", () => {
  const proj = buildDrawdownProjection({
    currentDrawdownFraction: FRACTION,
    haltFraction: HALT,
    equity: EQUITY,
    avgLossDollars: AVG_LOSS,
  });
  assert.ok(proj);
  assert.ok(Math.abs(proj.current_dd_pct - 6.41630158607052) < 1e-9);
  assert.equal(proj.max_drawdown_pct, 20);
  assert.equal(proj.trades_remaining, 20);
  assert.ok(Math.abs(proj.dollars_until_halt - 2094.01986) < 1e-4);
  assert.equal(
    haltGapSentence(proj.dollars_until_halt, proj.max_drawdown_pct),
    "Gap $2,094.02 to the 20% halt",
  );
  assert.ok(Math.abs(proj.peak_equity - PEAK) < 0.001);
  assert.ok(Math.abs(proj.peak_equity - EQUITY) > 1);
});

test("audit sentence names the matching 2026-07-31 ending balance", () => {
  const audit = haltPeakAuditSentence(EQUITY, FRACTION, [
    { date: "2026-07-22", equity: 15727.7163 },
    { date: "2026-07-31", equity: PEAK },
    { date: "2026-08-03", equity: 15057.8928 },
    { date: "2026-10-26", equity: EQUITY },
  ]);
  assert.equal(audit.matched, true);
  assert.equal(audit.peakDate, "2026-07-31");
  assert.equal(
    audit.sentence,
    "Peak $15,415.68 on 2026-07-31 · whole closed book · 90-day ending_balance · halt uses this",
  );
  assert.equal(audit.sentence.includes("15415.6828") || audit.sentence.includes("15,415.68"), true);
  assert.equal(audit.sentence.includes("12.08"), false);
  assert.equal(audit.sentence.includes("14426.5661"), false);
  assert.equal(audit.sentence.includes(`${EQUITY} the kill-switch peak`), false);
});

test("a tied distance keeps the later date", () => {
  const implied = EQUITY / (1 - FRACTION);
  const audit = haltPeakAuditSentence(EQUITY, FRACTION, [
    { date: "2026-07-01", equity: implied },
    { date: "2026-07-31", equity: implied },
  ]);
  assert.equal(audit.peakDate, "2026-07-31");
});

test("a history miss does not invent a date", () => {
  const audit = haltPeakAuditSentence(EQUITY, FRACTION, [
    { date: "2026-10-26", equity: EQUITY },
  ]);
  assert.equal(audit.matched, false);
  assert.equal(audit.peakDate, null);
  assert.match(audit.sentence, /history row did not match the halt peak/);
  assert.equal(/\d{4}-\d{2}-\d{2}/.test(audit.sentence), false);
  assert.equal(audit.sentence.includes("12.08"), false);
  assert.equal(audit.sentence.includes("14426.5661"), false);
});

const CURVE: EquityCurvePoint[] = [
  { date: "2026-07-22", equity: 15727.7163 },
  { date: "2026-07-31", equity: PEAK },
  { date: "2026-08-03", equity: 15057.8928 },
  { date: "2026-10-26", equity: EQUITY },
];

const POST_PEAK_LEDGER: ClosedTradeRow[] = [
  { exit_time: "2026-07-31T20:45:00+00:00", symbol: "MES", pnl: 277.25, status: "closed" },
  { exit_time: "2026-08-03T20:45:02+00:00", symbol: "MGC", pnl: -571.29, status: "closed" },
  { exit_time: "2026-08-16T10:04:19+00:00", symbol: "MES", pnl: -417.2095, status: "closed" },
  { exit_time: "2026-08-04T15:00:00+00:00", symbol: "SPY", pnl: 13.17, status: "closed" },
  { exit_time: "2026-08-04T15:00:00+00:00", symbol: "QQQ", pnl: -8.4894, status: "closed" },
  { exit_time: "2026-08-04T15:00:00+00:00", symbol: "TSLA", pnl: -7.7378, status: "closed" },
  { exit_time: "2026-08-04T15:00:00+00:00", symbol: "AAPL", pnl: 2.44, status: "closed" },
];

test("the July 31 row is inside on 2026-10-29 and gone on 2026-10-30", () => {
  const inside = peakWindowNote("2026-07-31", CURVE, EQUITY, "2026-10-29");
  assert.equal(inside.inside, true);
  assert.equal(inside.leavesOn, "2026-10-30");
  assert.equal(inside.nextDate, "2026-08-03");
  assert.equal(inside.nextEquity, 15057.8928);
  assert.ok(
    Math.abs(inside.previewFraction! - (15057.8928 - EQUITY) / 15057.8928) < 1e-12,
  );
  assert.match(inside.sentence, /This peak row leaves the 90-day window on 2026-10-30 UTC/);
  assert.match(inside.sentence, /Preview of the stored high that would remain/);
  assert.match(inside.sentence, /not the live halt/);
  assert.match(inside.sentence, /2026-08-03/);

  const outside = peakWindowNote("2026-07-31", CURVE, EQUITY, "2026-10-30");
  assert.equal(outside.inside, false);
  assert.match(outside.sentence, /This peak row left the 90-day window on 2026-10-30 UTC/);
});

test("a tied later high keeps the later date", () => {
  const note = peakWindowNote(
    "2026-07-31",
    [
      { date: "2026-08-01", equity: 50 },
      { date: "2026-08-02", equity: 50 },
    ],
    40,
    "2026-08-01",
  );
  assert.equal(note.nextDate, "2026-08-02");
});

test("a peak with no later point invents no percentage", () => {
  const note = peakWindowNote(
    "2026-07-31",
    [{ date: "2026-07-22", equity: 15727.7163 }, { date: "2026-07-31", equity: PEAK }],
    EQUITY,
    "2026-10-29",
  );
  assert.equal(note.nextDate, null);
  assert.equal(note.previewFraction, null);
  assert.match(note.sentence, /There is no later stored high/);
  assert.equal(note.sentence.includes("%"), false);
});

test("closed pnl after the peak date sums the known ledger", () => {
  const line = symbolSplitSentence(POST_PEAK_LEDGER, "2026-07-31");
  assert.equal(
    line,
    "Since that peak, closed pnl: MGC -$571.29 · MES -$417.21 · SPY $13.17 · QQQ -$8.49 · TSLA -$7.74 · AAPL $2.44 · this split does not change the halt",
  );
});

test("a full 500-row page that starts on the peak date prints no split", () => {
  const trades: ClosedTradeRow[] = Array.from({ length: 500 }, () => ({
    exit_time: "2026-08-01T00:00:00+00:00",
    symbol: "MGC",
    pnl: -1,
    status: "closed",
  }));
  assert.equal(symbolSplitSentence(trades, "2026-07-31", 500), null);

  trades[0] = {
    exit_time: "2026-07-01T00:00:00+00:00",
    symbol: "MGC",
    pnl: -1,
    status: "closed",
  };
  const line = symbolSplitSentence(trades, "2026-07-31", 500);
  assert.ok(line);
  assert.match(line!, /this split does not change the halt$/);
});

test("an included row missing pnl prints no split", () => {
  assert.equal(
    symbolSplitSentence(
      [
        { exit_time: "2026-08-02T00:00:00+00:00", symbol: "MGC", pnl: -1, status: "closed" },
        { exit_time: "2026-08-03T00:00:00+00:00", symbol: "MES", status: "closed" },
      ],
      "2026-07-31",
    ),
    null,
  );
});

test("payload equity_peak is labeled only when it disagrees", () => {
  assert.equal(equityPeakDisclaimer(undefined, PEAK), null);
  assert.equal(equityPeakDisclaimer(PEAK, PEAK), null);
  assert.equal(equityPeakDisclaimer(PEAK + 0.02, PEAK), null);
  const note = equityPeakDisclaimer(10000, PEAK);
  assert.ok(note);
  assert.match(note!, /payload equity_peak is not the halt peak/);
  assert.match(note!, /\$10,000\.00/);
});

test("card state is ready with the audit lines in order, or unavailable", () => {
  const ready = projectionCardState({
    safety: {
      portfolio_equity: EQUITY,
      drawdown_pct: FRACTION,
      drawdown_limit_pct: -0.2,
      equity_peak: 10000,
    },
    avgLossDollars: AVG_LOSS,
    points: CURVE,
    trades: POST_PEAK_LEDGER,
    asOf: "2026-10-27",
  });
  assert.equal(ready.status, "ready");
  if (ready.status !== "ready") return;
  assert.equal(ready.projection.trades_remaining, 20);
  assert.match(ready.peakAudit, /2026-07-31/);
  assert.match(ready.detailLines[0], /This peak row leaves the 90-day window on 2026-10-30 UTC/);
  assert.equal(ready.detailLines[1], "Gap $2,094.02 to the 20% halt");
  assert.match(ready.detailLines[2], /MGC -\$571\.29/);
  assert.match(ready.detailLines[2], /this split does not change the halt$/);
  assert.match(ready.detailLines[3], /payload equity_peak is not the halt peak/);

  const quiet = projectionCardState({
    safety: {
      portfolio_equity: EQUITY,
      drawdown_pct: FRACTION,
      drawdown_limit_pct: -0.2,
      equity_peak: PEAK,
    },
    avgLossDollars: AVG_LOSS,
    points: CURVE,
    trades: POST_PEAK_LEDGER,
    asOf: "2026-10-27",
  });
  assert.equal(quiet.status, "ready");
  if (quiet.status !== "ready") return;
  assert.equal(quiet.detailLines.some((line) => line.includes("payload equity_peak")), false);

  assert.equal(projectionCardState({
    failed: true,
    safety: { portfolio_equity: EQUITY, drawdown_pct: FRACTION, drawdown_limit_pct: -0.2 },
    avgLossDollars: AVG_LOSS,
    points: CURVE,
    trades: [],
    asOf: "2026-10-27",
  }).status, "unavailable");
  assert.equal(projectionCardState({
    safety: null,
    avgLossDollars: AVG_LOSS,
    points: CURVE,
    trades: [],
    asOf: "2026-10-27",
  }).status, "unavailable");
  assert.equal(projectionCardState({
    safety: { portfolio_equity: 0, drawdown_pct: FRACTION, drawdown_limit_pct: -0.2 },
    avgLossDollars: AVG_LOSS,
    points: CURVE,
    trades: [],
    asOf: "2026-10-27",
  }).status, "unavailable");
});

test("projection sources do not rebuild daily pnl", () => {
  const lib = readFileSync(new URL("../lib/drawdownProjection.ts", import.meta.url), "utf8");
  const card = readFileSync(
    new URL("../components/DrawdownProjectionCard.tsx", import.meta.url),
    "utf8",
  );
  for (const forbidden of ["normalizeDailyPnlRows", "571", "417.2095", "12.08", "15415.6828"]) {
    assert.equal(lib.includes(forbidden), false, forbidden);
    assert.equal(card.includes(forbidden), false, forbidden);
  }
  assert.equal(card.includes("days=90"), false);
  assert.equal(card.includes("EQUITY_CURVE_DAYS"), true);
  assert.equal(card.includes("PAPER_TRADES_LIMIT"), true);
  assert.equal(card.includes("fetchEngine"), true);
  assert.equal(PROJECTION_LOADING_COPY, "Loading projection…");
  assert.equal(PROJECTION_UNAVAILABLE_COPY, "Projection unavailable");
  assert.equal(card.includes("PROJECTION_LOADING_COPY"), true);
  assert.equal(card.includes("PROJECTION_UNAVAILABLE_COPY"), true);
});
