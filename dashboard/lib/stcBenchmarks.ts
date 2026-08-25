// HARDCODED STC backtest benchmarks captured from a prior validated walk-forward.
// These are static constants, NOT recomputed live — keep them clearly labelled as
// such wherever they render next to live RL OOS metrics (no implied parity).
//
// CAPTURED_AT is inferred from git history (`git log -S "STC_BENCHMARKS" -- dashboard/app/strategies/page.tsx`):
// the constant first appears in commit be8dcab (2026-04-02, "chore: sprint closeout") and its
// values have never changed since. No separate capture log exists for this backtest run, so
// treat CAPTURED_AT as "committed no later than" rather than a precise backtest timestamp.
export const CAPTURED_AT = "2026-04-02";

export const SOURCE = "STC pipeline walk-forward backtest (pre-RL baseline), values frozen — not re-derived or re-fetched";

export interface StcBenchmark {
  pf: number;
  sharpe: number;
  wr: number;
  symbol: string;
  tf: string;
}

export const STC_BENCHMARKS: Record<string, StcBenchmark> = {
  MNQ: { pf: 1.46, sharpe: 0.19, wr: 47.7, symbol: "MNQ", tf: "1h" },
  MCL: { pf: 1.83, sharpe: 0.15, wr: 60.0, symbol: "MCL", tf: "1h" },
  MGC: { pf: 2.60, sharpe: 2.04, wr: 51.1, symbol: "MGC", tf: "1d" },
  MES: { pf: 0.96, sharpe: -0.12, wr: 42.9, symbol: "MES", tf: "1h" },
};
