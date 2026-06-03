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

// ---- Realized P&L (honest, read-time deduped view) ----

export type RealizedTrade = {
  symbol: string;
  direction: string;
  entry_time: string | null;
  exit_time: string | null;
  pnl_usd: number;
  grade: string | null;
};

export type EngineSim = {
  ok: boolean;
  raw_rows: number;
  trades: number;
  net_realized: number;
  wins: number;
  losses: number;
  win_rate: number;
  gross_win: number;
  gross_loss: number;
  profit_factor: number;
  trade_list: RealizedTrade[];
  error?: string | null;
};

export type IbkrAccount = {
  account: string;
  as_of: string;
  is_demo: boolean;
  nav_total: number;
  cash: number;
  stock_value: number;
  realized_ytd: number;
  unrealized_total: number;
  unrealized_stocks: number;
  unrealized_futures: number;
  top_unrealized_position?: {
    symbol: string;
    description: string;
    cost_price: number;
    close_price: number;
    unrealized_pnl: number;
  };
  note: string;
};

export type RealizedPnl = {
  engine_sim: EngineSim;
  ibkr_account: IbkrAccount | null;
  headline: string;
  caveats: string[];
};

export async function fetchRealizedPnl(): Promise<RealizedPnl> {
  const res = await fetch(`${BASE}/master/trading/realized`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`trading realized ${res.status}`);
  return res.json();
}
