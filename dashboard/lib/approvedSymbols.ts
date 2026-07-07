/** Substrings matched against `symbol` + `_filename` when picking a dashboard backtest baseline. */
export const PREFERRED_BASELINE_SYMBOL_SUBSTRINGS = ["MCL", "MNQ"] as const;

export function matchesPreferredBaseline(symbolAndFilename: string): boolean {
  const u = symbolAndFilename.toUpperCase();
  return PREFERRED_BASELINE_SYMBOL_SUBSTRINGS.some((s) => u.includes(s));
}
