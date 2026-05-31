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

export type FinancesDetail = {
  net_worth: number;
  accounts: { name: string; org: string; balance: number; is_liability: boolean }[];
  spend_by_category: Record<string, number>;
  budget_status: { category: string; spent: number; limit: number; over_by: number }[];
  recent: { posted: string; amount: number; description: string; category: string }[];
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
