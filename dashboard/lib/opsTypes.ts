// Types for the private /ops page feed

export interface ProofBarProgress {
  clean_paper_sessions: number;
  scored_setups: number;
  avg_r: number | null;
  rule_breaks: number;
  sessions_met?: boolean | string;
  setups_met?: boolean | string;
  avg_r_met?: boolean | string;
  rule_breaks_met?: boolean | string;
}

export interface Strike {
  date: string;
  reason: string;
  severity: "minor" | "major";
  status?: "confirmed" | "pending";
  method_note?: string;
}

export interface LockoutStatus {
  active: boolean;
  end_date: string | null;
  reason: string | null;
}

export interface PaperJournalRow {
  date: string;
  symbol: string;
  direction: "long" | "short";
  entry_price: number;
  exit_price: number | null;
  r_multiple: number | null;
  notes: string;
}

export interface SystemHealth {
  tick_recorder_last_write: string | null;
  flow_feed_age_seconds: number | null;
  ib_gateway_status: "connected" | "disconnected" | "unknown";
  live_legal?: boolean;
}

export interface OpsFeedData {
  proof_bar: ProofBarProgress;
  strikes: Strike[];
  lockouts: LockoutStatus[];
  today_journal: PaperJournalRow[];
  system_health: SystemHealth;
  timestamp: string;
}
