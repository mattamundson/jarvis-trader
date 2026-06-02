export type DomainStatus = {
  domain: string;
  ok: boolean;
  summary: string;
  metrics: Record<string, unknown>;
  alerts: string[];
  error?: string | null;
  updated_ts: string;
};

export type MasterStatus = {
  domains: Record<string, DomainStatus>;
  system_ok: boolean;
  ts: string;
};

const BASE = process.env.NEXT_PUBLIC_MASTER_API_URL ?? "http://127.0.0.1:8030";
const KEY = process.env.NEXT_PUBLIC_MASTER_API_KEY ?? "";

export async function fetchMasterStatus(): Promise<MasterStatus> {
  const res = await fetch(`${BASE}/master/status`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`master-api ${res.status}`);
  return res.json();
}

export type Account = {
  name: string;
  org: string;
  balance: number;
  is_liability: boolean;
};

export type NetWorthPoint = {
  day: string;
  ts: number;
  net_worth: number;
  assets: number;
  liabilities: number;
};

export type MonthOverMonth = Record<
  string,
  { this: number; last: number; delta: number }
>;

export type FinancesDetail = {
  net_worth: number;
  accounts: Account[];
  accounts_by_org: Record<string, Account[]>;
  spend_by_category: Record<string, number>;
  budget_status: { category: string; spent: number; limit: number; over_by: number }[];
  recent: { posted: string; amount: number; description: string; category: string }[];
  net_worth_history: NetWorthPoint[];
  month_over_month: MonthOverMonth;
  top_merchants: { merchant: string; total: number }[];
};

export async function fetchFinancesDetail(): Promise<FinancesDetail> {
  const res = await fetch(`${BASE}/master/finances/detail`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`finances detail ${res.status}`);
  return res.json();
}

// ---- Scheduler (master-api in-process scheduler) ----

export type SchedulerJob = {
  name: string;
  interval_s: number;
  tier: string;
  last_run: string | null;
  last_status: string | null;
};

export type MasterSchedulerStatus = {
  running: boolean;
  jobs: SchedulerJob[];
};

export type SchedulerRun = {
  id: number;
  job: string;
  status: string; // ok | degraded | error | skipped
  started_ts: string;
  finished_ts: string | null;
  duration_ms: number | null;
  detail: string | null;
};

export type SchedulerRunsResponse = {
  runs: SchedulerRun[];
  count: number;
};

export async function fetchMasterSchedulerStatus(): Promise<MasterSchedulerStatus> {
  const res = await fetch(`${BASE}/master/scheduler/status`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`scheduler status ${res.status}`);
  return res.json();
}

export async function fetchMasterSchedulerRuns(
  limit = 8,
): Promise<SchedulerRunsResponse> {
  const res = await fetch(`${BASE}/master/scheduler/runs?limit=${limit}`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`scheduler runs ${res.status}`);
  return res.json();
}

const BASE2 = process.env.NEXT_PUBLIC_MASTER_API_URL ?? "http://127.0.0.1:8030";

export type CommandEvent =
  | { type: "tool"; name: string }
  | { type: "text"; text: string }
  | { type: "done" };

export function streamCommand(
  text: string,
  onEvent: (e: CommandEvent) => void,
  onClose: () => void,
): () => void {
  const es = new EventSource(`${BASE2}/master/command/stream?text=${encodeURIComponent(text)}`);
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data) as CommandEvent;
    onEvent(ev);
    if (ev.type === "done") {
      es.close();
      onClose();
    }
  };
  es.onerror = () => {
    es.close();
    onClose();
  };
  return () => es.close();
}
