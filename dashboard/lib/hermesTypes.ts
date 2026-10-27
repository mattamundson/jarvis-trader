// Hermes gates.json types for /api/ops adapter

export interface HermesCleanSessions {
  have: number;
  need: number;
  met: boolean | string;
}

export interface HermesScoredSetups {
  have: number;
  need: number;
  avg_R: number | null;
  met: boolean;
}

export interface HermesRuleBreaks {
  confirmed: number;
  method_note: string;
  pending: number;
  met: boolean;
}

export interface HermesOptions1R {
  clean: number;
  of: number;
  no_strikes_30d: boolean;
  met: boolean;
}

export interface HermesGoLive {
  clean_sessions: HermesCleanSessions;
  scored_setups: HermesScoredSetups;
  rule_breaks_30d: HermesRuleBreaks;
}

export interface HermesLockout {
  name: string;
  through?: string;
  since?: string;
  active: boolean;
  note: string;
}

export interface HermesE1 {
  counts_toward_20: boolean;
  flag: string | null;
  stop: number | null;
}

export interface HermesE1LogEntry {
  date: string;
  call: "long" | "short";
  points: number;
  ref_R: number;
  graded_ct: number;
}

export interface HermesStrike {
  date: string;
  bans: string;
  status: string;
  method_note?: string;
}

export interface HermesGatesData {
  pulled_ct: string;
  source: string;
  E: number;
  R: number;
  live_size: number;
  live_legal: boolean;
  go_live: HermesGoLive;
  options_1R: HermesOptions1R;
  lockouts: HermesLockout[];
  e1: HermesE1;
  e1_log?: HermesE1LogEntry[];
  strikes?: HermesStrike[];
}
