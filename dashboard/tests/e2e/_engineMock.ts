import type { Page } from "@playwright/test";

// Shape-aware engine mock for the table-driven smoke suite.
//
// WHY NOT A BLANKET `{}` CATCH-ALL
// command-center-golden-path.spec.ts documents this at length and it is the
// single most important thing to preserve here: a blanket `{}` is NOT a
// realistic degraded response. The real engine returns [] for list endpoints and
// {jobs: []} for the scheduler, so a `{}` catch-all makes pages crash on
// `t.slice is not a function` / `undefined.replace()` -- failures that have
// nothing to do with degraded-data handling and that MASK the assertion the test
// actually exists to make. A suite that red-screens for the wrong reason teaches
// you to ignore it.
//
// So: known contracts are declared in SHAPES below, a conservative heuristic
// covers list-vs-object for everything else, and `{}` remains only as the last
// resort. A route that fails *because* it hit the `{}` fallback is a mock-shape
// gap -- promote the real contract into SHAPES. It is never a reason to relax
// the assertion.
//
// THREE MODES
//   degraded - engine up, no data yet. Empty-but-correctly-shaped 200s.
//   offline  - engine unreachable. 503s, including /health, so the global
//              SystemFreshnessStrip flips to "Engine offline".
//   slow     - degraded bodies behind a delay, to catch loading states that
//              never resolve (a spinner that spins forever is a real defect and
//              is invisible to a fast mock).

export type MockMode = "degraded" | "offline" | "slow";

/** Long enough to out-live an initial render, short enough to keep 91 cases cheap. */
const SLOW_DELAY_MS = 1_200;

/** A price entry with no data -- the honest degraded shape, not a fabricated 0. */
const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

// Ordered: first match wins, so put specific patterns before general ones.
// Every entry here is a contract someone verified against the real engine.
// Provenance for the first four: command-center-golden-path.spec.ts.
const SHAPES: Array<[RegExp, unknown]> = [
  // --- verified against the real engine (see golden-path spec) --------------
  [/\/prices\/snapshot/, { MES: { symbol: "MES", ...NULL_PRICE }, MGC: { symbol: "MGC", ...NULL_PRICE } }],
  [/\/decisions\/recent/, []],
  [/\/portfolio\/history\/trades/, []],
  [/\/scheduler\/status/, { jobs: [] }],
  [
    // `diagnosis` is required and non-nullable; the page guards on `!journalStats`
    // but not on a truthy-but-empty object, so `{}` trips undefined.replace().
    /\/journal\/review\/stats/,
    {
      total_trades: 0,
      win_rate: 0,
      avg_win_usd: 0,
      avg_loss_usd: 0,
      risk_reward_ratio: 0,
      expected_value_usd: 0,
      trades_per_week: 0,
      diagnosis: "insufficient_data",
    },
  ],

  // --- health / status -----------------------------------------------------
  // Engine reachable and nominally healthy: in `degraded` mode the point is that
  // the ENGINE is up and the DATA is empty. Offline is a separate mode.
  [/\/health\/full/, { status: "ok", ib_gateway: { connected: true, data_source: "ibkr", consecutive_failures: 0 }, components: {} }],
  [/\/health$/, { status: "ok", tradingview_mcp_healthy: true, llm_path_healthy: true }],
  [/\/safety\/kill-switch/, { active: false, activated_at: null, reason: null }],
  [/\/safety\/circuit-breakers/, { breakers: [] }],
  [/\/safety\/status/, { kill_switch_active: false, breakers: [], account_value_usd: null }],
  [/\/market\/session/, { session: "closed", next_open: null }],

  // --- list endpoints whose consumers call .map/.slice ----------------------
  [/\/pipeline\/(history|recent-with-reasoning)/, []],
  [/\/watchlist$/, []],
  [/\/scanner\/signals\/latest/, []],
  [/\/learning\/memory/, []],
  [/\/wfe\/snapshots/, []],
  [/\/analytics\/mtf/, { timeframes: [] }],

  // mission-control panels. These are list endpoints whose last path segment is
  // singular ("ledger", "unrealized"), so the plural heuristic below cannot see
  // them and they fell through to `{}` -- which is what produced the
  // "r.map is not a function" crash on /mission-control in iteration 2. This is
  // the heuristic's known blind spot, and declaring the contract is the fix.
  //
  // strategy/ledger is NOT a bare list -- it's `LedgerResponse { entries: [...] }`
  // (lib/api.ts). A bare `[]` here is actively wrong, not just imprecise: both
  // consumers (ValidationGatesPanel, app/strategy-ledger/page.tsx) read
  // `ledger?.entries`, and `[].entries` resolves to Array.prototype.entries (a
  // real, truthy function) instead of undefined -- so `?? []` never fires and
  // the page tries to iterate a function, throwing "function is not iterable".
  // Found by iteration 7 (/strategy-ledger), which exercises this more directly
  // than mission-control's panel does.
  [/\/strategy\/ledger/, {
    entries: [],
    total: 0,
    n_pass: 0,
    n_fail: 0,
    generated_at: "",
    ledger_freshness: {
      status: "empty",
      basis: "none",
      newest_created_at: null,
      newest_source_file_mtime: null,
      entries_missing_created_at: 0,
      entries_with_source_file_mtime: 0,
    },
  }],
  [/\/portfolio\/paper\/positions\/unrealized/, []],
  [/\/portfolio\/paper\/performance/, { equity_curve: [], trades: [], summary: null }],
  [/\/pipeline\/status/, { stages: [], running: false }],

  // Consumers do Object.entries(by_regime).map and recommendations.slice().map
  // -- both undefined under a `{}` catch-all, which is the exact "not a
  // function" class this mock exists to avoid. Found by iteration 2.
  //
  // The real contract (SignalQualityResponse, lib/api.ts) wraps the totals
  // under `overall: SignalMetricsResponse`, not flat `total_signals` -- the
  // shape originally declared here invented a flat `total_signals`/`outcomes`
  // that the type doesn't have and omitted the required `overall`/`by_symbol`,
  // which QualityCard reads as `data.overall.total_signals` unconditionally.
  // Corrected while fixing iteration 9's calibration finding in this same file.
  [
    /\/analytics\/signal-quality/,
    {
      overall: {
        total_signals: 0,
        profitable_signals: 0,
        accuracy: 0,
        avg_signal_to_entry_minutes: 0,
        avg_entry_to_peak_minutes: 0,
        avg_pnl_per_signal: 0,
        best_time_of_day: "",
        worst_time_of_day: "",
      },
      by_symbol: {},
      by_regime: {},
      recommendations: [],
    },
  ],
  [/\/analytics\/signal-outcomes/, { outcomes: [], total: 0 }],

  // --- pipeline funnel (T9) --------------------------------------------------
  // PipelineFunnelCard reads data.windows["30"]/["90"] unconditionally once the
  // fetch resolves. A `{}` catch-all trips `undefined.windows` and the card
  // crashes into its widget boundary; the honest degraded shape is zeroed
  // windows with null conversion (the card renders dashes, not fabricated %).
  [
    /\/analytics\/pipeline-funnel/,
    {
      generated_at: "",
      cache_ttl_seconds: 300,
      windows: {
        "30": {
          days: 30, cutoff_utc: "", runs: 0, signals: 0, auto_signals: 0,
          human_signals: 0, queue_approved_raw: 0, approved: 0, executed: 0, filled: 0,
          conversion: {
            signal_rate_pct: null, approval_rate_pct: null, execution_rate_pct: null,
            fill_rate_pct: null, overall_fill_rate_pct: null,
          },
          notes: [],
        },
        "90": {
          days: 90, cutoff_utc: "", runs: 0, signals: 0, auto_signals: 0,
          human_signals: 0, queue_approved_raw: 0, approved: 0, executed: 0, filled: 0,
          conversion: {
            signal_rate_pct: null, approval_rate_pct: null, execution_rate_pct: null,
            fill_rate_pct: null, overall_fill_rate_pct: null,
          },
          notes: [],
        },
      },
    },
  ],

  // Object-wrapping-a-list, same trap as scheduler/status and pipeline/status
  // above: the LAST path segment ("regime-stats") ends in "s" so the plural
  // heuristic below fires and returns a bare `[]` -- but the real shape is
  // `{ regimes: [...], total_closed_trades: N }`, and RegimeAttributionWidget
  // calls `data.regimes.map` unconditionally (outside the loading/empty
  // guards), so `[].regimes` is undefined and crashes the same as `{}` would.
  // Found by iteration 6 (/stats [degraded], which redirects to /performance).
  [/\/journal\/regime-stats/, { regimes: [], total_closed_trades: 0 }],

  // ConfidenceGauge does `data.agents.filter(...)` unconditionally once `data`
  // is truthy -- "calibration" doesn't end in "s" so it falls to the `{}`
  // catch-all and `undefined.filter` throws. The honest degraded state IS the
  // real "not yet calibrated" shape (CalibrationDiagnostics), not an invented
  // number. Found by iteration 9 (/signal-outcomes [degraded]).
  [
    /\/analytics\/calibration/,
    {
      brier_enabled: false,
      brier_blend_alpha: 0,
      min_trades_threshold: 0,
      window_days: 30,
      agents: [],
      per_agent: {},
      total_outcomes: 0,
      ready_to_activate: false,
      active_agents: [],
      blocked_by: [],
      rows_excluded_corrupt: 0,
      rows_excluded_duplicate: 0,
      neutral_sentinel: 0,
      timestamp: "",
    },
  ],

  // --- aggregates -------------------------------------------------------------
  // Both entries below were previously invented shapes that don't match either
  // real contract at all (wrong field names entirely, not just imprecise
  // values) -- caught while root-causing iteration 13's /research-log crash.
  //
  // MarketSessionStatusCard reads `sessionData.gross_pnl.toFixed(2)` unconditionally
  // once the fetch resolves (its guard is `sessionData && !fetchError`, which the
  // old `{realized_pnl_usd, trade_count, unavailable}` shape satisfies -- it's a
  // truthy object -- so `gross_pnl` being absent threw "Cannot read properties of
  // undefined (reading 'toFixed')", white-screening the page into the global error
  // boundary. The real engine (portfolio_router.py:2503-2517) always returns a
  // full numeric row -- zero trades today is `gross_pnl: 0`, not an "unavailable"
  // sentinel; there is no unavailable state for this endpoint, only zero-rows.
  [
    /\/portfolio\/stats\/session-today/,
    {
      date: "",
      session: "EXTENDED",
      closed_trades: 0,
      open_trades: 0,
      gross_pnl: 0,
      wins: 0,
      losses: 0,
      win_rate: null,
      best_trade: null,
      worst_trade: null,
      avg_pnl: null,
      symbols_traded: [],
      last_updated: "",
    },
  ],
  // Real contract is PnlTruthResponse (pnl_truth_router.py / lib/api.ts) --
  // `{status, realized_pnl, closed_trades, excluded_trades, reasons,
  // sources_present, trusted}`. None of the old mock's keys exist on it, so
  // EnginePnlTruthCard's `data.trusted`/`data.realized_pnl`/`data.status` reads
  // were all silently reading `undefined`. DEGRADED + realized_pnl:null IS the
  // real fail-safe shape per the router's own docstring (missing/unreadable ledger).
  [
    /\/pnl\/truth/,
    {
      status: "DEGRADED",
      realized_pnl: null,
      closed_trades: 0,
      excluded_trades: 0,
      reasons: [],
      sources_present: [],
      trusted: false,
    },
  ],
];

/**
 * Last-segment heuristic for endpoints not in SHAPES. Deliberately conservative:
 * it only decides array-vs-object, never invents fields. Getting this wrong
 * surfaces as a route failure, which is the correct outcome -- it means a real
 * contract needs declaring above.
 */
const LIST_HINTS =
  /\/(recent|history|list|all|trades|signals|decisions|alerts|events|logs|snapshots|candidates|results|items|entries|positions|orders|jobs)\/?$/;

function bodyFor(pathname: string): unknown {
  for (const [re, body] of SHAPES) {
    if (re.test(pathname)) return body;
  }
  if (LIST_HINTS.test(pathname)) return [];
  // Plural last segment is a weak but useful signal for list endpoints.
  const last = pathname.split("?")[0].replace(/\/$/, "").split("/").pop() ?? "";
  if (/[a-z]s$/.test(last) && !/status|analysis|progress/.test(last)) return [];
  return {};
}

/**
 * Intercept every call the dashboard makes to the engine proxy.
 *
 * All engine traffic goes through app/api/engine/[...path]/route.ts, so this one
 * glob covers the whole surface -- and intercepting at the proxy boundary rather
 * than per-endpoint means a page that invents a new call still gets a plausible
 * response instead of a confusing network error.
 */
export async function installEngineMock(page: Page, mode: MockMode): Promise<void> {
  await page.route("**/api/engine/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;

    if (mode === "offline") {
      // Every endpoint including /health, so useEngineStatus flips isOnline to
      // false and the global SystemFreshnessStrip must show "Engine offline".
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "engine unreachable (e2e offline mode)" }),
      });
    }

    if (mode === "slow") {
      await new Promise((r) => setTimeout(r, SLOW_DELAY_MS));
    }

    return route.fulfill({ status: 200, json: bodyFor(pathname) as never });
  });
}

/**
 * Console errors that indicate a genuine React/JS fault, as opposed to the noise
 * a degraded backend legitimately produces (failed fetches, 503 warnings).
 *
 * Kept narrow ON PURPOSE. Widening it to all console.error would make the suite
 * fail on expected degraded-path logging and create pressure to disable the
 * check entirely -- which is how a suite quietly loses its teeth.
 */
export const FATAL_CONSOLE = /Minified React error|Hydration failed|TypeError|is not a function|Cannot read propert/;

/** Route-level error-boundary text. A page matching this white-screened. */
export const ERROR_BOUNDARY_TEXT = /something went wrong|application error|unhandled runtime error/i;

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (FATAL_CONSOLE.test(text)) errors.push(text);
  });
  page.on("pageerror", (err) => {
    // An uncaught exception is always fatal regardless of message shape.
    errors.push(`pageerror: ${err.message}`);
  });
  return errors;
}
