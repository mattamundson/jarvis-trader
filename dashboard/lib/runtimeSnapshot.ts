export interface RawRuntimeSnapshot {
  artifact?: string;
  schema_version?: number;
  captured_at_utc?: string;
  repository?: {
    head?: string | null;
    branch?: string | null;
    status_porcelain_count?: number | null;
  };
  ports?: {
    engine_8010_open?: boolean;
    dashboard_3010_open?: boolean;
    ib_paper_4002_open?: boolean;
    ib_live_4001_open?: boolean;
  };
  api?: {
    health?: {
      reachable?: boolean;
      safe_health?: {
        status?: string | null;
        live_trading?: boolean | null;
        paper_trading?: boolean | null;
        kill_switch_active?: boolean | null;
        ibkr_connected?: boolean | null;
      };
    };
    backup_status?: {
      reachable?: boolean;
      safe_health?: {
        healthy?: boolean | null;
        backup_count?: number | null;
        last_backup_age_hours?: number | null;
      };
    };
    eligibility?: {
      reachable?: boolean;
      summary?: {
        total?: number;
        tradeable?: number;
        enabled?: number;
        disagreements?: number;
      };
      symbols?: Array<{
        symbol?: string;
        enabled?: boolean;
        authorized?: boolean;
        tradeable?: boolean;
        config_agrees?: boolean;
        verdict?: string | null;
        verdict_age_days?: number | null;
      }>;
    };
  };
}

export interface RuntimeSnapshotSummary {
  available: boolean;
  source: "phase0_runtime_truth_snapshot";
  generated_at: string | null;
  age_seconds: number | null;
  freshness: "fresh" | "stale" | "unknown";
  repository: {
    branch: string | null;
    head_short: string | null;
    dirty_count: number | null;
  };
  ports: {
    engine_8010_open: boolean | null;
    dashboard_3010_open: boolean | null;
    ib_paper_4002_open: boolean | null;
    ib_live_4001_open: boolean | null;
  };
  engine: {
    reachable: boolean | null;
    status: string | null;
    live_trading: boolean | null;
    paper_trading: boolean | null;
    kill_switch_active: boolean | null;
    ibkr_connected: boolean | null;
  };
  backup: {
    reachable: boolean | null;
    healthy: boolean | null;
    backup_count: number | null;
    last_backup_age_hours: number | null;
  };
  eligibility: {
    reachable: boolean | null;
    total: number | null;
    tradeable: number | null;
    enabled: number | null;
    disagreements: number | null;
    enabled_not_tradeable: string[];
    disagreeing_symbols: string[];
  };
  findings: string[];
  errors: {
    load: string | null;
  };
}

const SNAPSHOT_STALE_AFTER_SECONDS = 24 * 60 * 60;

function toIso(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const ts = Date.parse(value);
  return Number.isNaN(ts) ? null : new Date(ts).toISOString();
}

function toBool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function toNum(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function toShortHead(value: unknown): string | null {
  return typeof value === "string" && value.length >= 7 ? value.slice(0, 12) : null;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort();
}

export function summarizeRuntimeSnapshot(
  raw: RawRuntimeSnapshot | null | undefined,
  nowMs = Date.now(),
  loadError: string | null = null
): RuntimeSnapshotSummary {
  const generatedAt = toIso(raw?.captured_at_utc);
  const ageSeconds = generatedAt ? Math.max(0, Math.floor((nowMs - Date.parse(generatedAt)) / 1000)) : null;
  const freshness =
    ageSeconds == null ? "unknown" : ageSeconds <= SNAPSHOT_STALE_AFTER_SECONDS ? "fresh" : "stale";

  const eligibilityRows = Array.isArray(raw?.api?.eligibility?.symbols) ? raw?.api?.eligibility?.symbols ?? [] : [];
  const enabledNotTradeable = uniqueSorted(
    eligibilityRows
      .filter((row) => row?.enabled === true && row?.tradeable === false && typeof row?.symbol === "string")
      .map((row) => row.symbol as string)
  );
  const disagreeingSymbols = uniqueSorted(
    eligibilityRows
      .filter((row) => row?.config_agrees === false && typeof row?.symbol === "string")
      .map((row) => row.symbol as string)
  );

  const summary: RuntimeSnapshotSummary = {
    available: !!raw && raw.artifact === "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
    source: "phase0_runtime_truth_snapshot",
    generated_at: generatedAt,
    age_seconds: ageSeconds,
    freshness,
    repository: {
      branch: typeof raw?.repository?.branch === "string" ? raw.repository.branch : null,
      head_short: toShortHead(raw?.repository?.head),
      dirty_count: toNum(raw?.repository?.status_porcelain_count),
    },
    ports: {
      engine_8010_open: toBool(raw?.ports?.engine_8010_open),
      dashboard_3010_open: toBool(raw?.ports?.dashboard_3010_open),
      ib_paper_4002_open: toBool(raw?.ports?.ib_paper_4002_open),
      ib_live_4001_open: toBool(raw?.ports?.ib_live_4001_open),
    },
    engine: {
      reachable: toBool(raw?.api?.health?.reachable),
      status: typeof raw?.api?.health?.safe_health?.status === "string" ? raw.api.health.safe_health.status : null,
      live_trading: toBool(raw?.api?.health?.safe_health?.live_trading),
      paper_trading: toBool(raw?.api?.health?.safe_health?.paper_trading),
      kill_switch_active: toBool(raw?.api?.health?.safe_health?.kill_switch_active),
      ibkr_connected: toBool(raw?.api?.health?.safe_health?.ibkr_connected),
    },
    backup: {
      reachable: toBool(raw?.api?.backup_status?.reachable),
      healthy: toBool(raw?.api?.backup_status?.safe_health?.healthy),
      backup_count: toNum(raw?.api?.backup_status?.safe_health?.backup_count),
      last_backup_age_hours: toNum(raw?.api?.backup_status?.safe_health?.last_backup_age_hours),
    },
    eligibility: {
      reachable: toBool(raw?.api?.eligibility?.reachable),
      total: toNum(raw?.api?.eligibility?.summary?.total),
      tradeable: toNum(raw?.api?.eligibility?.summary?.tradeable),
      enabled: toNum(raw?.api?.eligibility?.summary?.enabled),
      disagreements: toNum(raw?.api?.eligibility?.summary?.disagreements),
      enabled_not_tradeable: enabledNotTradeable,
      disagreeing_symbols: disagreeingSymbols,
    },
    findings: [],
    errors: {
      load: loadError,
    },
  };

  const findings: string[] = [];
  if (!summary.available) findings.push("Runtime snapshot artifact is missing or invalid.");
  if (summary.freshness === "stale") findings.push("Runtime snapshot is older than 24h.");
  if (summary.engine.reachable === false) findings.push("Engine HTTP health probe was unreachable at capture time.");
  if (summary.ports.engine_8010_open === false) findings.push("Engine port 8010 was closed at capture time.");
  if (summary.ports.dashboard_3010_open === true) findings.push("Dashboard port 3010 was open at capture time.");
  if (summary.ports.ib_paper_4002_open === false) findings.push("IB paper port 4002 was closed at capture time.");
  if (summary.ports.ib_live_4001_open === true) findings.push("[RISK] IB live port 4001 was open at capture time.");
  if (summary.engine.live_trading === true) findings.push("[RISK] Snapshot reported live_trading=true.");
  if (summary.engine.kill_switch_active === true) findings.push("Kill switch was active at capture time.");
  if ((summary.eligibility.disagreements ?? 0) > 0) {
    findings.push(
      `Eligibility had ${summary.eligibility.disagreements} config/runtime disagreement(s): ${summary.eligibility.disagreeing_symbols.join(", ") || "symbols unavailable"}.`
    );
  }
  if (summary.eligibility.enabled_not_tradeable.length > 0) {
    findings.push(
      `Enabled but not tradeable symbols: ${summary.eligibility.enabled_not_tradeable.join(", ")}.`
    );
  }
  if (summary.backup.reachable === false) findings.push("Backup-status endpoint was unreachable at capture time.");
  if (summary.backup.healthy === false) findings.push("Backup status was unhealthy at capture time.");
  if (loadError) findings.push(`Snapshot load error: ${loadError}`);

  summary.findings = findings;
  return summary;
}
