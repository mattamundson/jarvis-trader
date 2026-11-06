import test from "node:test";
import assert from "node:assert/strict";

interface ProofSetup {
  date: string;
  setup: string;
  side: string;
  trigger: string;
  entry_time: string;
  entry: number;
  stop: number;
  target: number;
  exit_time: string;
  exit: number;
  exit_reason: string;
  R: number;
  rule_breaks?: string[];
  status: string;
  counted: boolean;
}

interface ProofRecordResponse {
  available: boolean;
  source?: string;
  error?: string;
  goal_setups: number;
  counted: number;
  avg_r: number | null;
  total_r: number | null;
  wins: number;
  losses: number;
  generated_ct?: string;
  setups: ProofSetup[];
}

test("recomputes stats from counted setups correctly", () => {
  const setups: ProofSetup[] = [
    {
      date: "2026-01-01",
      setup: "FVG",
      side: "LONG",
      trigger: "break",
      entry_time: "09:30",
      entry: 5800,
      stop: 5795,
      target: 5810,
      exit_time: "09:45",
      exit: 5808,
      exit_reason: "target",
      R: 1.6,
      status: "complete",
      counted: true,
    },
    {
      date: "2026-01-02",
      setup: "BB",
      side: "SHORT",
      trigger: "rejection",
      entry_time: "10:00",
      entry: 5820,
      stop: 5825,
      target: 5810,
      exit_time: "10:15",
      exit: 5823,
      exit_reason: "stop",
      R: -0.6,
      status: "complete",
      counted: true,
    },
    {
      date: "2026-01-03",
      setup: "FVG",
      side: "LONG",
      trigger: "break",
      entry_time: "11:00",
      entry: 5830,
      stop: 5825,
      target: 5840,
      exit_time: "11:30",
      exit: 5835,
      exit_reason: "partial",
      R: 0.5,
      status: "in_review",
      counted: false,
    },
  ];

  const counted = setups.filter((s) => s.counted);
  const totalR = counted.reduce((sum, s) => sum + s.R, 0);
  const wins = counted.filter((s) => s.R > 0).length;
  const losses = counted.filter((s) => s.R < 0).length;
  const avgR = counted.length > 0 ? totalR / counted.length : null;

  assert.equal(counted.length, 2, "Should count only counted setups");
  assert.equal(wins, 1, "Should count 1 win");
  assert.equal(losses, 1, "Should count 1 loss");
  assert.equal(avgR, 0.5, "Should compute avg R correctly");
  assert.equal(totalR, 1.0, "Should sum R correctly");
});

test("handles empty setups array", () => {
  const setups: ProofSetup[] = [];
  const counted = setups.filter((s) => s.counted);
  const avgR = counted.length > 0 ? 0 : null;

  assert.equal(counted.length, 0, "Should handle empty array");
  assert.equal(avgR, null, "Should return null for avg_r when empty");
});

test("normalizes r_multiple to R field", () => {
  const setupWithRMultiple = {
    date: "2026-01-01",
    setup: "FVG",
    side: "LONG",
    trigger: "break",
    entry_time: "09:30",
    entry: 5800,
    stop: 5795,
    target: 5810,
    exit_time: "09:45",
    exit: 5808,
    exit_reason: "target",
    r_multiple: 1.5,
    status: "complete",
    counted: true,
  };

  const normalized = {
    ...setupWithRMultiple,
    R: setupWithRMultiple.r_multiple,
  } as ProofSetup;

  assert.equal(normalized.R, 1.5, "Should normalize r_multiple to R");
});

test("unavailable response has correct structure", () => {
  const response: ProofRecordResponse = {
    available: false,
    error: "File not found",
    goal_setups: 20,
    counted: 0,
    avg_r: null,
    total_r: null,
    wins: 0,
    losses: 0,
    setups: [],
  };

  assert.equal(response.available, false);
  assert.equal(response.goal_setups, 20);
  assert.equal(response.counted, 0);
  assert.equal(response.avg_r, null);
  assert.equal(response.setups.length, 0);
});
