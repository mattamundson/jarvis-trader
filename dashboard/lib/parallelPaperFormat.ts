// Pure display-formatting helpers for /parallel-paper. Extracted out of
// app/parallel-paper/page.tsx (a "use client" component with JSX) so they can
// be unit-tested directly with node:test's --experimental-strip-types, which
// strips TS types only and cannot parse JSX.
//
// GT-08 fix: fmtPct's old "already in percent form" branch
// (`if (Math.abs(val) > 2) return val.toFixed(1) + "%"`) silently divided any
// real drawdown fraction with |val| > 2 by 100. GET /portfolio/paper/account/
// {id}/stats (engine/routers/portfolio_router.py) always returns max_dd as a
// true fraction of running peak, e.g. -2.0032 for a -200.32% drawdown -- it
// never pre-multiplies by 100. A -2.0032 max_dd rendered as "-2.0%" instead of
// "-200.3%", understating a real risk figure by 100x. Fractions this large are
// possible when the equity curve's peak is small in dollar terms (this
// endpoint's "equity" is cumulative P&L starting at 0, not account NAV) --
// the assumption that a valid fraction can't exceed +/-2 was wrong.

export function fmt(val: number | null | undefined, decimals = 2, suffix = ""): string {
  if (val == null) return "—";
  return `${val.toFixed(decimals)}${suffix}`;
}

export function fmtPct(val: number | null | undefined): string {
  if (val == null) return "—";
  if (!isFinite(val) || isNaN(val)) return "—";
  // Values from this endpoint are always fractions, never pre-multiplied
  // percents -- always scale by 100. Only reject magnitudes so extreme
  // (>100,000%) that they indicate genuinely corrupted upstream data, not a
  // legitimate (if severe) drawdown or ratio.
  if (Math.abs(val) > 1000) return "—(data err)";
  return `${(val * 100).toFixed(1)}%`;
}

// Calmar is floored engine-side (portfolio_router.py CALMAR_MIN_DD_FLOOR) so a
// near-zero max_dd no longer explodes the ratio, but clamp here too as
// defense-in-depth against a future upstream regression -- same pattern as
// fmtPct's magnitude clamp above.
export function fmtCalmar(val: number | null | undefined): string {
  if (val == null) return "—";
  if (!isFinite(val) || isNaN(val)) return "—";
  if (Math.abs(val) > 1000) return "—(data err)";
  return fmt(val);
}

export function statColor(val: number | null | undefined, higherBetter = true): string {
  if (val == null) return "text-muted-foreground";
  const positive = higherBetter ? val > 0 : val < 0;
  return positive ? "text-green-400" : "text-red-400";
}
