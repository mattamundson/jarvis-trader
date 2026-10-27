// Adapter to convert Hermes gates.json to OpsFeedData
import type { HermesGatesData, HermesE1LogEntry } from "./hermesTypes";
import type { OpsFeedData, PaperJournalRow, Strike } from "./opsTypes";

export function adaptHermesToOps(hermes: HermesGatesData): OpsFeedData {
  // Map go_live to proof_bar
  const proofBar = {
    clean_paper_sessions: hermes.go_live.clean_sessions.have,
    scored_setups: hermes.go_live.scored_setups.have,
    avg_r: hermes.go_live.scored_setups.avg_R,
    rule_breaks: hermes.go_live.rule_breaks_30d.confirmed + hermes.go_live.rule_breaks_30d.pending,
  };

  // Map strikes (if present)
  const strikes: Strike[] = (hermes.strikes || []).map((s) => ({
    date: s.date,
    reason: s.bans,
    severity: s.status === "major" ? "major" : "minor",
  }));

  // Map lockouts
  const activeLockout = hermes.lockouts.find((l) => l.active);
  const lockout = {
    active: !!activeLockout,
    end_date: activeLockout?.through || null,
    reason: activeLockout?.note || null,
  };

  // Map e1_log to journal rows (if present)
  const todayJournal: PaperJournalRow[] = (hermes.e1_log || []).map((entry) => ({
    date: entry.date,
    symbol: "E1",
    direction: entry.call,
    entry_price: entry.points,
    exit_price: null,
    r_multiple: entry.ref_R,
    notes: `Graded CT: ${entry.graded_ct}${hermes.e1.counts_toward_20 ? " • Pre-holdout" : ""}`,
  }));

  // System health derived from Hermes metadata
  const systemHealth = {
    tick_recorder_last_write: hermes.pulled_ct,
    flow_feed_age_seconds: Math.floor((Date.now() - new Date(hermes.pulled_ct).getTime()) / 1000),
    ib_gateway_status: hermes.live_legal ? ("connected" as const) : ("disconnected" as const),
  };

  return {
    proof_bar: proofBar,
    strikes,
    lockout,
    today_journal: todayJournal,
    system_health: systemHealth,
    timestamp: hermes.pulled_ct,
  };
}

// Verify E field is never included in the output
export function verifyNoMoneyInOutput(data: OpsFeedData): boolean {
  const serialized = JSON.stringify(data);
  // Check that no E field or dollar amounts appear
  // This is a runtime safeguard, not a compile-time check
  return !serialized.includes('"E"') && !serialized.includes("$");
}
