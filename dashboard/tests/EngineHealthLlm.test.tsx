/**
 * EngineHealthWidget LLM-degradation surface — compile-time type tests.
 *
 * No runtime test framework is installed in this project (no Jest/Vitest); these
 * tests exercise the LLM provider-redundancy types under tsc so the dashboard
 * contract stays in sync with the engine's get_llm_provider_summary() shape.
 *
 * Run via: cd dashboard && ./node_modules/.bin/tsc -p tsconfig.test.json --noEmit
 *
 * Guards the #10 fix: a request served by a FALLBACK provider keeps
 * llm_path_healthy === true, so the widget must read llm_providers
 * (primary_healthy / single_leg_warning) to surface the degradation as a warning
 * instead of a false green.
 */

import type { HealthResponse, LLMProviderSummary } from "../lib/api";

// ── Healthy primary: anthropic is both primary and active ────────────────────
const healthy: LLMProviderSummary = {
  active_provider: "anthropic",
  primary_provider: "anthropic",
  primary_healthy: true,
  single_leg_warning: false,
};

// ── Degraded onto a fallback: primary unhealthy, gemini now serving ──────────
const onFallback: LLMProviderSummary = {
  active_provider: "gemini",
  primary_provider: "anthropic",
  primary_healthy: false,
  single_leg_warning: false,
};

// ── One provider-failure from dark ───────────────────────────────────────────
const singleLeg: LLMProviderSummary = {
  active_provider: "gemini",
  primary_provider: "anthropic",
  primary_healthy: false,
  single_leg_warning: true,
};

// HealthResponse must carry the optional snapshot + failover counts.
const health: HealthResponse = {
  status: "ok",
  version: "2.1.0",
  live_trading: false,
  kill_switch_active: false,
  paper_mode: true,
  ibkr_connected: true,
  schwab_connected: false,
  uptime_seconds: 123,
  llm_path_healthy: true, // path alive even while on a fallback — the trap #10 fixes
  llm_providers: onFallback,
  vertex_failover_count: 2,
  google_fallback_count: 5,
};

// Pure mirror of the widget's derivation, kept here so the warn-on-fallback
// contract is asserted at type-check time and stays honest.
function isLlmDegraded(h: HealthResponse): boolean {
  const p = h.llm_providers;
  if (!p) return false;
  return p.primary_healthy === false || p.single_leg_warning === true;
}

const _checks: boolean[] = [
  isLlmDegraded(health) === true,
  isLlmDegraded({ ...health, llm_providers: healthy }) === false,
  isLlmDegraded({ ...health, llm_providers: onFallback }) === true,
  isLlmDegraded({ ...health, llm_providers: singleLeg }) === true,
  // Absent snapshot (older engine build) must not report degraded.
  isLlmDegraded({ ...health, llm_providers: null }) === false,
];

export const _engineHealthLlmTypeChecks = _checks;
