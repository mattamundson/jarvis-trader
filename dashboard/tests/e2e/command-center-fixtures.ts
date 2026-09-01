import type { Page } from "@playwright/test";

export type CommandCenterFixtureMode = "offline" | "degraded" | "empty" | "populated";

const NULL_PRICE = {
  last_price: null,
  prev_close: null,
  change_pct: null,
  error: "No data available",
};

const JOURNAL_EMPTY = {
  total_trades: 0,
  win_rate: 0,
  avg_win_usd: 0,
  avg_loss_usd: 0,
  risk_reward_ratio: 0,
  expected_value_usd: 0,
  trades_per_week: 0,
  diagnosis: "insufficient_data",
};

const PAPER_STATUS_EMPTY = {
  MES_1h: { symbol: "MES", status: "ACTIVE", authorized: true, verdict: "PASS", wfe_label: "1.00" },
  MGC_1d: { symbol: "MGC", status: "ACTIVE", authorized: true, verdict: "PASS", wfe_label: "1.00" },
  MCL_1h: { symbol: "MCL", status: "NO-TRADE", authorized: false, verdict: "FAIL", reason: "fixture halted" },
  MNQ_1h: { symbol: "MNQ", status: "NO-TRADE", authorized: false, verdict: "FAIL", reason: "fixture halted" },
};

const PIPELINE_FUNNEL_EMPTY = {
  generated_at: "",
  cache_ttl_seconds: 300,
  windows: {
    "30": {
      days: 30,
      cutoff_utc: "",
      runs: 0,
      signals: 0,
      auto_signals: 0,
      human_signals: 0,
      queue_approved_raw: 0,
      approved: 0,
      executed: 0,
      filled: 0,
      conversion: {
        signal_rate_pct: null,
        approval_rate_pct: null,
        execution_rate_pct: null,
        fill_rate_pct: null,
        overall_fill_rate_pct: null,
      },
      notes: [],
    },
    "90": {
      days: 90,
      cutoff_utc: "",
      runs: 0,
      signals: 0,
      auto_signals: 0,
      human_signals: 0,
      queue_approved_raw: 0,
      approved: 0,
      executed: 0,
      filled: 0,
      conversion: {
        signal_rate_pct: null,
        approval_rate_pct: null,
        execution_rate_pct: null,
        fill_rate_pct: null,
        overall_fill_rate_pct: null,
      },
      notes: [],
    },
  },
};

const MASTER_STATUS_EMPTY = {
  domains: {},
  system_ok: true,
  ts: "2026-09-01T00:00:00.000Z",
  aggregation_ok: true,
  stale_domains: [],
};

const REALIZED_EMPTY = {
  engine_sim: {
    ok: true,
    net_realized: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    profit_factor: null,
    gross_win: 0,
    gross_loss: 0,
    trades: 0,
    raw_rows: 0,
    trade_list: [],
  },
  ibkr_account: null,
  headline: "No realized paper trades",
  caveats: [],
};

const ENGINE_POPULATED: Array<[RegExp, unknown]> = [
  [/\/portfolio$/, { total_equity: 10125, daily_pnl: 125, cash: 10000, positions: [] }],
  [/\/decisions\/recent/, [
    {
      timestamp: "2026-09-01T14:31:00.000Z",
      symbol: "MES",
      action: "BUY",
      reason: "fixture trend continuation",
      signal: "long",
      regime: "TREND",
      quantity: 1,
      price: 5421.25,
    },
  ]],
  [/\/portfolio\/history\/trades/, [
    {
      timestamp: "2026-09-01T15:02:00.000Z",
      symbol: "MES",
      action: "BUY",
      quantity: 1,
      price: 5421.25,
      pnl: 125,
      commission: 2.4,
    },
  ]],
  [/\/scheduler\/status/, {
    running: true,
    jobs: [{ name: "pipeline-scan", last_run: "2026-09-01T15:00:00.000Z", next_run: null, running: false }],
    total_decisions_logged: 1,
    last_scan: "2026-09-01T15:00:00.000Z",
    next_scan: null,
  }],
  [/\/system\/data-integrity/, {
    timestamp: "2026-09-01T15:00:00.000Z",
    count: 2,
    sources: [
      { source: "bars", last_update: "2026-09-01T15:00:00.000Z", latency_sec: 0.5, status: "healthy" },
      { source: "prices", last_update: "2026-09-01T15:00:00.000Z", latency_sec: 0.2, status: "healthy" },
    ],
  }],
  [/\/strategy\/ledger/, {
    entries: [
      {
        symbol: "MES",
        family: "vwap",
        rank: 1,
        verdict: "FAIL",
        passed_via: null,
        core_verdict: "FAIL",
        alt_verdict: null,
        created_at: "2026-09-01T00:00:00.000Z",
        pf_ci_lower: 0.57,
        p_edge: 0.41,
        mc_95th_dd_pct: 7.47,
        dsr: 0,
        wfo_consistency: "WEAK",
        fixed_params_min_pf: 0.26,
        cost_survives_through: "none",
        oos_trades: 237,
        source_file: "MES_vwap_rank1.json",
        source_file_mtime: "2026-09-01T00:00:00.000Z",
        freshness_status: "reported",
        freshness_basis: "created_at",
        next_gate: "repair thesis",
        next_gate_reason: "fixture failure requires repair before rerun",
      },
    ],
    total: 1,
    n_pass: 0,
    n_fail: 1,
    generated_at: "2026-09-01T00:00:00.000Z",
    ledger_freshness: {
      status: "reported",
      basis: "created_at",
      newest_created_at: "2026-09-01T00:00:00.000Z",
      newest_source_file_mtime: "2026-09-01T00:00:00.000Z",
      entries_missing_created_at: 0,
      entries_with_source_file_mtime: 1,
    },
  }],
];

const ENGINE_EMPTY: Array<[RegExp, unknown]> = [
  [/\/prices\/snapshot/, { MES: { symbol: "MES", ...NULL_PRICE }, MGC: { symbol: "MGC", ...NULL_PRICE } }],
  [/\/analyze\/bars\//, { bars: [] }],
  [/\/health$/, {
    status: "ok",
    kill_switch_active: false,
    uptime_seconds: 0,
    ibkr_connected: false,
    paper_trading: true,
    version: "fixture",
    execution_connected_verified: false,
    execution_path: { connected: false, simulated: false, source: "fixture" },
  }],
  [/\/safety\/status/, {
    daily_pnl: 0,
    equity_peak: 10000,
    drawdown_pct: 0,
    orders_last_minute: 0,
    consecutive_losses: 0,
    kill_switch_active: false,
    daily_limit_pct: -0.02,
    drawdown_limit_pct: -0.1,
    orders_per_minute_limit: 10,
  }],
  [/\/portfolio$/, { total_equity: 10000, daily_pnl: 0, cash: 10000, positions: [] }],
  [/\/decisions\/recent/, []],
  [/\/portfolio\/history\/trades/, []],
  [/\/pipeline\/pending-approvals/, { pending: [], count: 0 }],
  [/\/scheduler\/status/, { running: false, jobs: [], total_decisions_logged: 0, last_scan: null, next_scan: null }],
  [/\/macro\/snapshot/, { vix: null, vix_regime: null, regime: null, timestamp: null }],
  [/\/backtest\/paper-status/, PAPER_STATUS_EMPTY],
  [/\/journal\/review\/stats/, JOURNAL_EMPTY],
  [/\/system\/data-integrity/, { timestamp: "2026-09-01T00:00:00.000Z", count: 0, sources: [] }],
  [/\/strategy\/ledger/, {
    entries: [],
    total: 0,
    n_pass: 0,
    n_fail: 0,
    generated_at: "2026-09-01T00:00:00.000Z",
    ledger_freshness: {
      status: "empty",
      basis: "none",
      newest_created_at: null,
      newest_source_file_mtime: null,
      entries_missing_created_at: 0,
      entries_with_source_file_mtime: 0,
    },
  }],
  [/\/pipeline\/actionable/, { items: [], count: 0, available: true, raw_count: 0, shown: 0 }],
  [/\/analytics\/pipeline-funnel/, PIPELINE_FUNNEL_EMPTY],
  [/\/analytics\/regime\//, { current_regime: "UNKNOWN", regime: "UNKNOWN" }],
];

function engineBodyFor(pathname: string, mode: Exclude<CommandCenterFixtureMode, "offline">): unknown {
  if (mode === "populated") {
    for (const [re, body] of ENGINE_POPULATED) {
      if (re.test(pathname)) return body;
    }
  }

  for (const [re, body] of ENGINE_EMPTY) {
    if (re.test(pathname)) return body;
  }

  if (mode === "degraded") return {};
  return {};
}

function masterBodyFor(pathname: string): unknown {
  if (/\/master\/status$/.test(pathname)) return MASTER_STATUS_EMPTY;
  if (/\/master\/trading\/realized$/.test(pathname)) return REALIZED_EMPTY;
  return {};
}

export async function installCommandCenterFixture(
  page: Page,
  mode: CommandCenterFixtureMode = "empty",
): Promise<void> {
  await page.route("**/api/engine/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (mode === "offline") {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "engine unreachable (command-center fixture)" }),
      });
    }
    return route.fulfill({ status: 200, json: engineBodyFor(pathname, mode) as never });
  });

  await page.route("**/api/master/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (mode === "offline") {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "master-api unreachable (command-center fixture)" }),
      });
    }
    return route.fulfill({ status: 200, json: masterBodyFor(pathname) as never });
  });
}
