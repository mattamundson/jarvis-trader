"use client";

import { useLLMHealth } from "@/hooks/useLLMHealth";

/**
 * Small fixed badge (bottom-right) showing which LLM provider is serving.
 * Green when healthy on the primary leg; amber when on a fallback leg or one
 * failure from going dark (single_leg_warning); red when the path is unhealthy
 * or status is unknown. Hidden until /health/full carries the US-004 llm
 * subsystem (older engine => no badge, no crash).
 *
 * Does not collide with the banners: IBDataDegradedBanner is top, and
 * EngineOfflineBanner only shows when the engine is unreachable — at which point
 * /health/full has no signal and this badge is hidden.
 */
export function LLMProviderBadge() {
  const { provider, fallbackActive, status, healthy, singleLegWarning, hasSignal } =
    useLLMHealth();

  if (!hasSignal) return null;

  const unhealthy = status === "unknown" || healthy === false;
  const warn = fallbackActive || singleLegWarning;

  // red > amber > green
  const palette = unhealthy
    ? { bg: "#7f1d1d", border: "#b91c1c", dot: "#fca5a5", fg: "#fee2e2" }
    : warn
      ? { bg: "#78350f", border: "#b45309", dot: "#fcd34d", fg: "#fffbeb" }
      : { bg: "#14532d", border: "#15803d", dot: "#86efac", fg: "#ecfdf5" };

  const label = (provider ?? "—").toUpperCase();
  const suffix = unhealthy
    ? "unhealthy"
    : fallbackActive
      ? "fallback"
      : singleLegWarning
        ? "single leg"
        : null;

  const title = unhealthy
    ? "LLM path unhealthy — see /health"
    : fallbackActive
      ? `Serving on fallback leg (${label}); primary is degraded`
      : singleLegWarning
        ? "One provider failure from going dark"
        : `LLM primary serving (${label})`;

  return (
    <div
      role="status"
      aria-live="polite"
      title={title}
      className="fixed bottom-2 right-2 z-[9990] flex items-center gap-1.5 rounded-full px-2.5 py-1 shadow-md select-none"
      style={{ backgroundColor: palette.bg, border: `1px solid ${palette.border}` }}
    >
      <span
        className={`inline-block w-2 h-2 rounded-full ${warn || unhealthy ? "animate-pulse" : ""}`}
        style={{ backgroundColor: palette.dot }}
      />
      <span className="font-mono text-[11px] font-semibold leading-none" style={{ color: palette.fg }}>
        LLM {label}
        {suffix && (
          <span className="font-normal opacity-80">{` · ${suffix}`}</span>
        )}
      </span>
    </div>
  );
}
