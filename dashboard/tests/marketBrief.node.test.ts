import assert from "node:assert/strict";
import { test } from "node:test";

import { extractMachinePayload, summarizeMachinePayload } from "@/lib/marketBrief/summary";

const fixtureMarkdown = `# Machine-scored morning market brief preview

### Market machine payload (JSON)
\`\`\`json
{
  "generated_at": "2026-09-11T01:00:00",
  "scores": {
    "status": "computed",
    "macro_event_count": 3,
    "inputs": { "trend_score": 0.6, "vol_score": 1, "macro_score": 0.8 },
    "probabilities": { "continuation": 79.5, "rotation": 20.5, "failure": 0 },
    "notes": ["Scenario engine note"]
  },
  "symbols": {
    "ES=F": { "provider": "yahoo", "confidence": 0.8, "gap_pct": 0.3, "daily": { "last_close": 7621.25 }, "pivots": { "pivot": 7616.75, "r1": 7648, "s1": 7567.25 } },
    "NQ=F": { "provider": "yahoo", "confidence": 0.8, "gap_pct": 0.2, "daily": { "last_close": 29194.75 }, "pivots": { "pivot": 29228.92, "r1": 29414.58, "s1": 28949.58 } },
    "SPY": { "provider": "yahoo", "confidence": 1, "gap_pct": -0.6, "daily": { "last_close": 757.83 }, "pivots": { "pivot": 762.6, "r1": 764.27, "s1": 760.74 } },
    "QQQ": { "provider": "yahoo", "confidence": 1, "gap_pct": -1.06, "daily": { "last_close": 708.69 }, "pivots": { "pivot": 716.68, "r1": 719.33, "s1": 713.65 } },
    "^VIX": { "provider": "yahoo", "confidence": 1, "gap_pct": 8.38, "daily": { "last_close": 17.84 }, "pivots": { "pivot": 16.24 } }
  }
}
\`\`\`
`;

test("extractMachinePayload reads fenced JSON after the market payload marker", () => {
  const payload = extractMachinePayload(fixtureMarkdown);
  assert.ok(payload);
  assert.equal((payload.scores as { status?: string }).status, "computed");
});

test("summarizeMachinePayload preserves analysis-only contract and key probabilities", () => {
  const payload = extractMachinePayload(fixtureMarkdown);
  const generated = Date.parse("2026-09-11T01:00:00");
  const summary = summarizeMachinePayload(payload, {
    sourcePath: "C:/brief.md",
    nowMs: generated + 60_000,
  });
  assert.equal(summary.mode, "ANALYSIS_ONLY");
  assert.equal(summary.orders_enabled, false);
  assert.equal(summary.risk_config_touched, false);
  assert.equal(summary.sourceQuality, "fresh");
  assert.equal(summary.scores.probabilities.continuation, 79.5);
  assert.equal(summary.scores.probabilities.rotation, 20.5);
  assert.equal(summary.scores.probabilities.failure, 0);
  assert.equal(summary.symbols.SPY.gap_pct, -0.6);
  assert.equal(summary.levels.find((level) => level.symbol === "ES=F")?.pivot, 7616.75);
});

test("summarizeMachinePayload degrades and warns when payload is missing", () => {
  const summary = summarizeMachinePayload(null, { sourcePath: null, loadError: "missing artifact" });
  assert.equal(summary.sourceQuality, "degraded");
  assert.ok(summary.warnings.some((warning) => warning.includes("missing artifact")));
  assert.equal(summary.scores.probabilities.continuation, 0);
});

test("summarizeMachinePayload marks old artifacts stale", () => {
  const payload = extractMachinePayload(fixtureMarkdown);
  const generated = Date.parse("2026-09-11T01:00:00");
  const summary = summarizeMachinePayload(payload, {
    sourcePath: "C:/brief.md",
    nowMs: generated + 19 * 60 * 60 * 1000,
  });
  assert.equal(summary.sourceQuality, "stale");
  assert.ok(summary.warnings.some((warning) => warning.includes("stale")));
});
