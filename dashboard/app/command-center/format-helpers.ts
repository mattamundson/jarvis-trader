// Pure formatting + honesty-gate helpers for the command-center flagship page.
// Extracted from page.tsx (P5.1) so they're importable from a plain .ts test
// file — page.tsx is JSX (.tsx) and can't be loaded by Node's native
// TS-stripping test runner, which erases type annotations but doesn't
// transform JSX. Byte-identical logic, no behavior change.

export function fmtUSD(n: number | undefined | null): string {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
}

export function fmtPct(n: number | undefined | null, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(decimals) + "%";
}

export function fmtUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

export function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

export function pnlColor(n: number | undefined | null): string {
  if (n == null) return "text-gray-400";
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-gray-300";
}

// Suspect-price honesty (folded from /trust, P2.1). A futures entry below
// its per-symbol floor is almost certainly a corrupted field (the 2026-06-12
// MES@100.5 STC-leak class), not a real price. Conservative — only flags the
// obviously-impossible, never a real price.
export const PRICE_FLOORS: Record<string, number> = {
  MES: 1000, ES: 1000, MNQ: 1000, NQ: 1000, MGC: 500, GC: 500, MCL: 5, CL: 5,
};
export function suspectPrice(symbol: string, price: number): boolean {
  const floor = PRICE_FLOORS[(symbol || "").toUpperCase()];
  return floor != null && price > 0 && price < floor;
}
