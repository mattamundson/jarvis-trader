import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number, decimals = 2): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatPercent(value: number, decimals = 2): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export function formatNumber(value: number, decimals = 0): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function signalToLabel(signal: number): string {
  if (signal >= 0.5) return "STRONG BUY";
  if (signal >= 0.2) return "BUY";
  if (signal >= -0.2) return "NEUTRAL";
  if (signal >= -0.5) return "SELL";
  return "STRONG SELL";
}

export function signalToColor(signal: number): string {
  if (signal >= 0.2) return "text-bull";
  if (signal <= -0.2) return "text-bear";
  return "text-warn";
}
