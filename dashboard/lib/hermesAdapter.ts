// Adapter to convert Hermes gates.json to OpsFeedData
import type { HermesGatesData } from "./hermesTypes";
import type { OpsFeedData, PaperJournalRow, Strike, LockoutStatus } from "./opsTypes";

export function adaptHermesToOps(hermes: HermesGatesData): OpsFeedData {
  // Map go_live to proof_bar with all met fields
  const proofBar = {
    clean_paper_sessions: hermes.go_live.clean_sessions.have,
    scored_setups: hermes.go_live.scored_setups.have,
    avg_r: hermes.go_live.scored_setups.avg_R,
    rule_breaks: hermes.go_live.rule_breaks_30d.confirmed + hermes.go_live.rule_breaks_30d.pending,
    sessions_met: hermes.go_live.clean_sessions.met,
    setups_met: hermes.go_live.scored_setups.met,
    avg_r_met: hermes.go_live.scored_setups.avg_R !== null && hermes.go_live.scored_setups.avg_R > 0,
    rule_breaks_met: hermes.go_live.rule_breaks_30d.met,
  };

  // Map strikes with status field
  const strikes: Strike[] = (hermes.strikes ?? []).map((s) => ({
    date: s.date,
    reason: s.bans,
    severity: s.status === "confirmed" ? "major" : "minor",
    status: s.status as "confirmed" | "pending",
    method_note: s.method_note,
  }));

  // Map lockouts array (not single lockout)
  const lockouts: LockoutStatus[] = hermes.lockouts.map((lock) => ({
    active: lock.active,
    end_date: lock.through ?? lock.since ?? null,
    reason: lock.note,
  }));

  // Map e1_log to today_journal
  const todayJournal: PaperJournalRow[] = (hermes.e1_log ?? []).map((entry) => ({
    date: entry.date,
    symbol: "MES",
    direction: entry.call,
    entry_price: 0,
    exit_price: null,
    r_multiple: entry.points / entry.ref_R,
    notes: hermes.e1.counts_toward_20 ? "Holdout E1 row" : "Pre-holdout E1 row",
  }));

  return {
    proof_bar: proofBar,
    strikes,
    lockouts,
    today_journal: todayJournal,
    system_health: {
      tick_recorder_last_write: null,
      flow_feed_age_seconds: null,
      ib_gateway_status: "unknown",
      live_legal: hermes.live_legal,
    },
    timestamp: hermes.pulled_ct,
  };
}

// Verify E field is never included in the output
export function verifyNoMoneyInOutput(data: OpsFeedData): boolean {
  const serialized = JSON.stringify(data);
  return !serialized.includes('"E"') && !serialized.includes("$");
}
