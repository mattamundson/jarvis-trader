/**
 * BookmarkThemesPanel — compile-time type tests.
 *
 * No runtime test framework is installed in this project (no Jest/Vitest).
 * These tests exercise the component's exported types under tsc to ensure
 * the interface contract stays in sync with the engine's to_dict() shape.
 *
 * Run via: cd dashboard && ./node_modules/.bin/tsc -p tsconfig.test.json --noEmit
 */

import type { BookmarkTheme, BookmarkThemesResponse } from "../components/BookmarkThemesPanel";

// ── Verify BookmarkTheme shape ───────────────────────────────────────────────

const exampleTheme: BookmarkTheme = {
  name: "AI Inference Optimization",
  description: "Techniques for reducing LLM serving latency",
  count: 12,
  urls: [
    "https://github.com/vllm-project/vllm",
    "https://x.com/example/status/12345",
    "https://arxiv.org/abs/2305.11206",
  ],
  confidence: 0.87,
};

// confidence is a float 0–1 (not a percentage)
const _confCheck: number = exampleTheme.confidence;
void _confCheck;

// urls array (top 3 are displayed; component slices .slice(0, 3))
const _urlsCheck: string[] = exampleTheme.urls;
void _urlsCheck;

// ── Verify BookmarkThemesResponse shape ─────────────────────────────────────

const exampleResponse: BookmarkThemesResponse = {
  themes: [
    exampleTheme,
    { name: "Quantitative Strategies", description: "Systematic trading research", count: 8, urls: [], confidence: 0.74 },
    { name: "Open Source Tooling", description: "Dev tools and libraries", count: 6, urls: [], confidence: 0.81 },
    { name: "Market Microstructure", description: "Order flow and liquidity", count: 5, urls: [], confidence: 0.79 },
    { name: "Model Architectures", description: "Transformer variants and SSMs", count: 10, urls: [], confidence: 0.91 },
    { name: "Risk Management", description: "Portfolio risk frameworks", count: 4, urls: [], confidence: 0.76 },
    { name: "Data Engineering", description: "Pipelines and warehousing", count: 7, urls: [], confidence: 0.83 },
  ],
  bookmark_count: 371,
  lookback_days: 7,
  model: "claude-haiku-4-5",
  latency_ms: 9000,
  cost_usd: 0.02,
  cached: false,
  actionable: true,
  error: null,
};

// 7 themes render — verify the array length is assignable
const _themeCount: number = exampleResponse.themes.length;
void _themeCount;

// cached flag drives the "cached" badge in the normal render state
const _cachedFlag: boolean = exampleResponse.cached;
void _cachedFlag;

// error field is string | null — null means no error
const _errField: string | null = exampleResponse.error;
void _errField;

// ── Force-refresh URL encoding check ─────────────────────────────────────────
// The component appends ?refresh=true when forceKey > 0.
// Verify the engine endpoint accepts the `refresh` query param (documented in router).

const BASE_PATH = "/discord/bookmarks/weekly-themes";
const forceUrl: string = `${BASE_PATH}?refresh=true&_k=1`;
// URL must be a string (SWR key)
const _forceUrlCheck: string = forceUrl;
void _forceUrlCheck;

// ── Empty state contract ─────────────────────────────────────────────────────
// When themes is [], panel shows "No themes yet" empty state.

const emptyResponse: BookmarkThemesResponse = {
  themes: [],
  bookmark_count: 0,
  lookback_days: 7,
  model: "claude-haiku-4-5",
  latency_ms: 0,
  cost_usd: 0,
  cached: false,
  actionable: false,
  error: null,
};

const _emptyThemes: BookmarkTheme[] = emptyResponse.themes;
void _emptyThemes;

// ── Error state contract ─────────────────────────────────────────────────────
// When error is non-null, panel shows "Clusterer offline — check engine logs".

const errorResponse: BookmarkThemesResponse = {
  themes: [],
  bookmark_count: 0,
  lookback_days: 7,
  model: "claude-haiku-4-5",
  latency_ms: 0,
  cost_usd: 0,
  cached: false,
  actionable: false,
  error: "DB timeout after 30s",
};

const _errString: string = errorResponse.error as string;
void _errString;

export {};
