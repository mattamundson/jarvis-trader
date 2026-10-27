// Terminal palette for /tape. Green / red / amber are reserved for STATE (side of a gate, pass/fail,
// freshness). Everything else is grey/blue-grey so colour keeps meaning something.
export const C = {
  bg: "#06080b",
  panel: "#0b0f14",
  line: "#18202a",
  grid: "#121922",
  text: "#c5ced8",
  dim: "#667386",
  faint: "#3a4553",
  green: "#3fb950",
  red: "#f85149",
  amber: "#d29922",
  series: "#9fb3c8",
  price: "#5b7089",
} as const;

export const MONO = "font-mono tabular-nums";

export function nf(v: number | null | undefined, dp = 2, signed = false): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return signed && v > 0 ? `+${s}` : s;
}

export function ctHM(epochS: number, withSec = false): string {
  return new Date(epochS * 1000).toLocaleTimeString("en-US", {
    timeZone: "America/Chicago", hour12: false, hour: "2-digit", minute: "2-digit", ...(withSec ? { second: "2-digit" } : {}),
  });
}

export function stateColor(kind: "up" | "down" | "warn" | "none"): string {
  return kind === "up" ? C.green : kind === "down" ? C.red : kind === "warn" ? C.amber : C.dim;
}
