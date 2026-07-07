/** Static instrument defaults; live rows merge with `/backtest/paper-status` in the page.
 *  Mirrors live gate-v2 reality: MES/MGC trend = PASS (active forward-proving book);
 *  MCL/MNQ = DO_NOT_TRADE (routing-blocked). The `wfe` field (kept as-is for backend/API
 *  parity) is displayed to users as "Deflated Sharpe" / "DSR" — it is gate-v2's deflated
 *  Sharpe ratio, NOT true walk-forward efficiency. `regime`/`lastSignal`/`atr` have no
 *  live backend source (PaperStatusRow carries only status/wfe) and are rendered as
 *  static/approximate in the UI. Live API values override wfe/status on load. */

export const INSTRUMENTS = [
  {
    symbol: "MES",
    tf: "1h",
    status: "APPROVED" as const,
    wfe: 1.0,
    regime: "TREND",
    lastSignal: "—",
    atr: "~5.2",
  },
  {
    symbol: "MGC",
    tf: "1d",
    status: "APPROVED" as const,
    wfe: 1.0,
    regime: "TREND",
    lastSignal: "—",
    atr: "~9.2",
  },
  {
    symbol: "MCL",
    tf: "1h",
    status: "HALTED" as const,
    wfe: 0.0,
    regime: "BLOCKED",
    lastSignal: "—",
    atr: "~0.42",
  },
  {
    symbol: "MNQ",
    tf: "1h",
    status: "HALTED" as const,
    wfe: 0.0,
    regime: "BLOCKED",
    lastSignal: "—",
    atr: "~18.5",
  },
];

export const WFE_ROWS = [
  { symbol: "MES", tf: "1h", wfe: 1.0, threshold: 0.3, status: "PASS" as const },
  { symbol: "MGC", tf: "1d", wfe: 1.0, threshold: 0.3, status: "PASS" as const },
  { symbol: "MCL", tf: "1h", wfe: 0.0, threshold: 0.3, status: "OVERFIT" as const },
  { symbol: "MNQ", tf: "1h", wfe: 0.0, threshold: 0.3, status: "OVERFIT" as const },
];
