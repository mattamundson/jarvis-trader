/** Static instrument / WFE defaults; live rows merge with `/backtest/paper-status` in the page. */

export const INSTRUMENTS = [
  {
    symbol: "MCL",
    tf: "1h",
    status: "APPROVED" as const,
    wfe: 0.82,
    regime: "BULL",
    lastSignal: "LONG",
    atr: "~0.42",
  },
  {
    symbol: "MNQ",
    tf: "1h",
    status: "APPROVED" as const,
    wfe: 0.57,
    regime: "NEUTRAL",
    lastSignal: "FLAT",
    atr: "~18.5",
  },
  {
    symbol: "MGC",
    tf: "1d",
    status: "HALTED" as const,
    wfe: 0.88,
    regime: "OVERFIT",
    lastSignal: "—",
    atr: "~9.2",
  },
];

export const WFE_ROWS = [
  { symbol: "MCL", tf: "1h", wfe: 0.82, threshold: 0.3, status: "PASS" as const },
  { symbol: "MNQ", tf: "1h", wfe: 0.57, threshold: 0.3, status: "PASS" as const },
  { symbol: "MGC", tf: "1d", wfe: 0.88, threshold: 0.3, status: "OVERFIT" as const },
];
