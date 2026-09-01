export type ResearchIntakeKind =
  | "pr"
  | "issue"
  | "experiment"
  | "spike"
  | "backlog"
  | "research_verdict";

export type ResearchIntakeDisposition =
  | "keep"
  | "split"
  | "replace"
  | "reference"
  | "retire_to_archive"
  | "defer";

export type ResearchIntakeReadinessImpact = "none";

export interface ResearchIntakeSource {
  system: "github" | "master_plan" | "engine";
  ref: string;
  branch?: string;
  url?: string;
}

export interface ResearchIntakeRow {
  id: string;
  kind: ResearchIntakeKind;
  title: string;
  source: ResearchIntakeSource;
  status: string;
  classification: string;
  disposition: ResearchIntakeDisposition;
  phase: string;
  readiness_impact: ResearchIntakeReadinessImpact;
  next_action: string;
  evidence: string[];
  updated_at: string;
}

export interface ResearchIntakeSummary {
  total: number;
  byDisposition: Record<ResearchIntakeDisposition, number>;
  readinessImpactRows: number;
}

const DISPOSITIONS: ResearchIntakeDisposition[] = [
  "keep",
  "split",
  "replace",
  "reference",
  "retire_to_archive",
  "defer",
];

const DISPOSITION_EVIDENCE = [
  "docs/plans/master-implementation/PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md",
];

export const RESEARCH_INTAKE_ROWS: ResearchIntakeRow[] = [
  {
    id: "pr-749",
    kind: "pr",
    title: "research: feature integrity registry and golden-vector parity",
    source: {
      system: "github",
      ref: "#749",
      branch: "research/feature-integrity-v2",
      url: "https://github.com/mattamundson/jarvis-trader/pull/749",
    },
    status: "draft",
    classification: "Research foundation candidate",
    disposition: "keep",
    phase: "Phase 2",
    readiness_impact: "none",
    next_action: "Inspect failing checks, run focused feature-registry/parity tests, then decide whether Phase 2 adopts it.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "pr-754",
    kind: "pr",
    title: "feat: Command Center V2 paper trading control plane",
    source: {
      system: "github",
      ref: "#754",
      branch: "feature/command-center-v2-paper",
      url: "https://github.com/mattamundson/jarvis-trader/pull/754",
    },
    status: "draft",
    classification: "Command Center reference spike",
    disposition: "reference",
    phase: "Phase 5",
    readiness_impact: "none",
    next_action: "Extract API contracts, UI lessons, and safety constraints into the Command Center build.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "pr-756",
    kind: "pr",
    title: "feat: paper trade-intent preview and submission foundation",
    source: {
      system: "github",
      ref: "#756",
      branch: "feature/trade-intent-paper-api",
      url: "https://github.com/mattamundson/jarvis-trader/pull/756",
    },
    status: "draft",
    classification: "Trade-intent / OMS reference spike",
    disposition: "reference",
    phase: "Phase 5",
    readiness_impact: "none",
    next_action: "Extract lifecycle and idempotency concepts after the OMS contract is approved.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "pr-755",
    kind: "pr",
    title: "[safety-review] indicators.py: restore Saty Phase Oscillator EMA3 smoothing",
    source: {
      system: "github",
      ref: "#755",
      branch: "safety-review/phase-ema3-smoothing",
      url: "https://github.com/mattamundson/jarvis-trader/pull/755",
    },
    status: "open",
    classification: "Source-parity safety review",
    disposition: "keep",
    phase: "Validation",
    readiness_impact: "none",
    next_action: "Inspect CI failures and rerun affected local checks before merge consideration.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "issue-750",
    kind: "issue",
    title: "Research: execute and harden PR #749 feature-integrity suite",
    source: {
      system: "github",
      ref: "#750",
      url: "https://github.com/mattamundson/jarvis-trader/issues/750",
    },
    status: "open",
    classification: "Feature-governance hardening",
    disposition: "keep",
    phase: "Phase 2",
    readiness_impact: "none",
    next_action: "Execute and harden the PR #749 feature-integrity suite.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "issue-751",
    kind: "issue",
    title: "Validation defect: current Initial Balance backfills completed IB into premarket bars",
    source: {
      system: "github",
      ref: "#751",
      url: "https://github.com/mattamundson/jarvis-trader/issues/751",
    },
    status: "open",
    classification: "Validation defect",
    disposition: "keep",
    phase: "Phase 2",
    readiness_impact: "none",
    next_action: "Write acceptance and patch the Initial Balance point-in-time leak.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "issue-752",
    kind: "issue",
    title: "Validation defect: VWAP gate path can trade premarket on near-continuous Globex cache",
    source: {
      system: "github",
      ref: "#752",
      url: "https://github.com/mattamundson/jarvis-trader/issues/752",
    },
    status: "open",
    classification: "Validation defect",
    disposition: "keep",
    phase: "Phase 2",
    readiness_impact: "none",
    next_action: "Write acceptance and patch VWAP premarket/session semantics.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "issue-753",
    kind: "issue",
    title: "Command Center V2: real-time paper trading control plane",
    source: {
      system: "github",
      ref: "#753",
      url: "https://github.com/mattamundson/jarvis-trader/issues/753",
    },
    status: "open",
    classification: "Command Center product epic",
    disposition: "keep",
    phase: "Phase 5",
    readiness_impact: "none",
    next_action: "Convert into a milestone-backed epic after GitHub write scope is approved.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
  {
    id: "issue-310",
    kind: "issue",
    title: "Dashboard: ES auction / overnight-bias card",
    source: {
      system: "github",
      ref: "#310",
      url: "https://github.com/mattamundson/jarvis-trader/issues/310",
    },
    status: "open",
    classification: "Advisory dashboard tile",
    disposition: "defer",
    phase: "Phase 5+",
    readiness_impact: "none",
    next_action: "Keep lower priority than trust, data, and risk surfaces.",
    evidence: DISPOSITION_EVIDENCE,
    updated_at: "2026-09-01",
  },
];

export function summarizeResearchIntake(rows: ResearchIntakeRow[] = RESEARCH_INTAKE_ROWS): ResearchIntakeSummary {
  const byDisposition = Object.fromEntries(DISPOSITIONS.map((disposition) => [disposition, 0])) as Record<
    ResearchIntakeDisposition,
    number
  >;
  let readinessImpactRows = 0;

  for (const row of rows) {
    byDisposition[row.disposition] += 1;
    if (row.readiness_impact !== "none") readinessImpactRows += 1;
  }

  return {
    total: rows.length,
    byDisposition,
    readinessImpactRows,
  };
}

export function commandCenterResearchIntakeRows(limit = 4): ResearchIntakeRow[] {
  return RESEARCH_INTAKE_ROWS.slice(0, limit);
}
