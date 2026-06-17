"use client";

/**
 * OFFLINE FALLBACK PRIMITIVE
 * Single component for all engine-offline degraded states.
 * Replaces the patchwork of 20+ different "engine offline" messages.
 *
 * Variants:
 *   card    — Full rounded card with amber border, icon, message (replaces red 502 boxes)
 *   inline  — Single line with gray dot + message (replaces inline error text)
 *   minimal — Just the dot indicator, no text (for dense widgets / table cells)
 *
 * In production: never shows API endpoint paths.
 * In development: shows the endpoint below the message in gray.
 */

import React from "react";
import { WifiOff, RefreshCw } from "lucide-react";

const isDev = process.env.NODE_ENV !== "production";

export interface OfflineFallbackProps {
  /** Human-readable message. Defaults to "Engine offline" */
  message?: string;
  /** API endpoint — only shown in development builds */
  endpoint?: string;
  /** Content to show alongside/below the offline state (e.g. stale data) */
  children?: React.ReactNode;
  /** Rendering variant */
  variant?: "card" | "inline" | "minimal";
  /** Show a retry button */
  showRetry?: boolean;
  /** Callback when retry is clicked */
  onRetry?: () => void;
  /** Additional className */
  className?: string;
}

export function OfflineFallback({
  message = "Engine offline",
  endpoint,
  children,
  variant = "inline",
  showRetry = false,
  onRetry,
  className = "",
}: OfflineFallbackProps) {
  if (variant === "minimal") {
    return (
      <span
        className={`inline-flex h-2 w-2 rounded-full flex-shrink-0 ${className}`}
        style={{ backgroundColor: "#555" }}
        title={message}
      />
    );
  }

  if (variant === "inline") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <span
          className="h-1.5 w-1.5 rounded-full flex-shrink-0"
          style={{ backgroundColor: "#555" }}
        />
        <span className="text-xs font-mono" style={{ color: "#555" }}>
          {message}
        </span>
        {isDev && endpoint && (
          <span className="text-[10px] font-mono" style={{ color: "#333" }}>
            · {endpoint}
          </span>
        )}
        {showRetry && onRetry && (
          <button
            onClick={onRetry}
            className="ml-1 flex items-center gap-1 text-[10px] font-mono transition-colors"
            style={{ color: "#555" }}
            onMouseEnter={e => (e.currentTarget.style.color = "#888")}
            onMouseLeave={e => (e.currentTarget.style.color = "#555")}
          >
            <RefreshCw className="h-2.5 w-2.5" />
            retry
          </button>
        )}
        {children}
      </div>
    );
  }

  // variant === "card"
  return (
    <div
      className={`rounded-widget p-4 flex flex-col gap-2 ${className}`}
      style={{
        backgroundColor: "#0d0d1a",
        border: "1px solid #ffaa0015",
      }}
    >
      <div className="flex items-center gap-2">
        <WifiOff className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "#555" }} />
        <span className="text-xs font-mono font-medium" style={{ color: "#555" }}>
          {message}
        </span>
        {showRetry && onRetry && (
          <button
            onClick={onRetry}
            className="ml-auto flex items-center gap-1 text-[10px] font-mono rounded px-2 py-1 transition-colors"
            style={{ color: "#888", backgroundColor: "#1a1a2e" }}
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = "#2a2a45")}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = "#1a1a2e")}
          >
            <RefreshCw className="h-2.5 w-2.5" />
            Retry
          </button>
        )}
      </div>
      {isDev && endpoint && (
        <span className="text-[10px] font-mono" style={{ color: "#333" }}>
          {endpoint}
        </span>
      )}
      {children}
    </div>
  );
}

// ── DataCell ──────────────────────────────────────────────────────────────────
/**
 * Typed value display with consistent offline/null handling.
 * Replaces the ~100 instances of `{value ?? "—"}` patterns.
 */

export interface DataCellProps {
  value: string | number | null | undefined;
  offline?: boolean;
  format?: (v: string | number) => string;
  color?: string;
  className?: string;
  placeholder?: string;
}

export function DataCell({
  value,
  offline = false,
  format,
  color,
  className = "",
  placeholder = "—",
}: DataCellProps) {
  if (offline || value === null || value === undefined) {
    return (
      <span
        className={`font-mono tabular-nums ${className}`}
        style={{ color: "#333" }}
      >
        {placeholder}
      </span>
    );
  }

  const display = format ? format(value) : String(value);

  return (
    <span
      className={`font-mono tabular-nums ${className}`}
      style={color ? { color } : undefined}
    >
      {display}
    </span>
  );
}

// ── StaleIndicator ────────────────────────────────────────────────────────────
/**
 * Shows when data was last updated. Turns amber when stale (>5 min).
 */

export interface StaleIndicatorProps {
  lastUpdated: Date | null | undefined;
  staleThresholdMs?: number;
  className?: string;
}

export function StaleIndicator({
  lastUpdated,
  staleThresholdMs = 5 * 60 * 1000,
  className = "",
}: StaleIndicatorProps) {
  if (!lastUpdated) return null;

  const ageMs = Date.now() - lastUpdated.getTime();
  const isStale = ageMs > staleThresholdMs;

  const ageLabel = ageMs < 60_000
    ? `${Math.round(ageMs / 1000)}s ago`
    : ageMs < 3600_000
    ? `${Math.round(ageMs / 60_000)}m ago`
    : `${Math.round(ageMs / 3600_000)}h ago`;

  return (
    <span
      className={`text-[10px] font-mono ${className}`}
      style={{ color: isStale ? "#ffaa00" : "#555" }}
      title={`Last updated: ${lastUpdated.toLocaleTimeString()}`}
    >
      {isStale ? `stale ${ageLabel}` : ageLabel}
    </span>
  );
}
