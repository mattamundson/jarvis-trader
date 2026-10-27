// Single source of truth for dashboard route coverage.
//
// `tests/routeManifest.node.test.ts` walks dashboard/app and asserts the set of
// page.tsx files equals ROUTES exactly. That is what keeps coverage honest as
// routes are added: a new route with no manifest entry FAILS the unit suite,
// rather than silently going untested.
//
// Landmarks: many pages render a generic "JARVIS TRADER" <h1> shared by ~17
// routes, which cannot distinguish "the right page rendered" from "some other
// page rendered". Those carry `landmark: null` and are counted by the ratchet in
// the manifest test so the number can only go down. Do not invent a landmark
// that is not actually on the page -- an assertion that passes everywhere is
// worse than none, because it reads as coverage.

export type RouteKind = "page" | "redirect" | "dynamic";

/** critical  - operator acts on this; a wrong render can cause a bad trading decision
 *  standard  - real operational surface, but not directly decision-bearing
 *  research  - exploratory/analytical; must carry an exploratory provenance banner */
export type Criticality = "critical" | "standard" | "research";

export interface RouteSpec {
  path: string;
  name: string;
  kind: RouteKind;
  criticality: Criticality;
  /** Distinctive visible text proving THIS page rendered. null = not yet distinctive. */
  landmark: RegExp | null;
  /** For kind === "redirect": where it must land. */
  target?: string;
  /** For kind === "dynamic": a concrete path to exercise. */
  samplePath?: string;
}

export const ROUTES: RouteSpec[] = [
  // ---- redirects -----------------------------------------------------------
  // NOTE: `/` is a server redirect, not a page. It renders nothing of its own.
  // Consequence worth knowing: homepage.spec.ts and homepage-golden-path.spec.ts
  // both navigate to "/" and therefore actually exercise /command-center -- the
  // same page command-center.spec.ts and command-center-golden-path.spec.ts
  // cover. Four specs, one route. Consolidating them is tracked separately.
  { path: "/", name: "root redirect", kind: "redirect", criticality: "critical", landmark: null, target: "/command-center" },
  { path: "/stats", name: "stats redirect", kind: "redirect", criticality: "standard", landmark: null, target: "/performance" },
  { path: "/trades/journal", name: "trades journal redirect", kind: "redirect", criticality: "standard", landmark: null, target: "/journal" },
  // Added by PR #558. Its page.tsx comment claims a client-side navigation but the
  // code calls the server-side redirect() -- the comment is wrong, the behaviour is
  // a server redirect, which is what this entry asserts. Filed as a follow-up.
  { path: "/dashboard", name: "dashboard alias redirect", kind: "redirect", criticality: "standard", landmark: null, target: "/command-center" },

  // ---- critical: operator decision surfaces --------------------------------
  { path: "/command-center", name: "command center", kind: "page", criticality: "critical", landmark: /JARVIS TRADER.*COMMAND CENTER/i },
  { path: "/command-center-v2", name: "command center v2", kind: "page", criticality: "critical", landmark: /Command Center V2/i },
  { path: "/command-center-v2/trade", name: "command center v2 manual trade intent", kind: "page", criticality: "critical", landmark: /Manual Paper Trade Intent/i },
  { path: "/trades/pending-approvals", name: "pending approvals", kind: "page", criticality: "critical", landmark: /Pending trade approvals/i },
  { path: "/paper", name: "paper trading", kind: "page", criticality: "critical", landmark: null },
  { path: "/portfolio", name: "portfolio", kind: "page", criticality: "critical", landmark: null },
  { path: "/performance", name: "performance", kind: "page", criticality: "critical", landmark: null },
  { path: "/validation", name: "validation", kind: "page", criticality: "critical", landmark: null },
  { path: "/trading-eligibility", name: "trading eligibility", kind: "page", criticality: "critical", landmark: /Trading Eligibility/i },
  { path: "/health", name: "system health", kind: "page", criticality: "critical", landmark: null },
  { path: "/trust-pane", name: "trust pane", kind: "page", criticality: "critical", landmark: /Trust Pane/i },
  { path: "/mission-control", name: "mission control", kind: "page", criticality: "critical", landmark: /MISSION CONTROL/i },
  { path: "/options", name: "options", kind: "page", criticality: "critical", landmark: null },
  { path: "/trades", name: "trade history", kind: "page", criticality: "critical", landmark: /Trade History/i },
  { path: "/signals", name: "trade signals", kind: "page", criticality: "critical", landmark: /Trade Signals/i },

  // ---- standard ------------------------------------------------------------
  { path: "/today", name: "today", kind: "page", criticality: "standard", landmark: /Today at a Glance/i },
  { path: "/journal", name: "trade journal", kind: "page", criticality: "standard", landmark: /Trade Journal/i },
  { path: "/watchlist", name: "watchlist", kind: "page", criticality: "standard", landmark: null },
  { path: "/settings", name: "settings", kind: "page", criticality: "standard", landmark: null },
  { path: "/config", name: "config", kind: "page", criticality: "standard", landmark: null },
  { path: "/scorecard", name: "scorecard", kind: "page", criticality: "standard", landmark: null },
  { path: "/strategies", name: "strategies", kind: "page", criticality: "standard", landmark: null },
  { path: "/discord", name: "discord intelligence", kind: "page", criticality: "standard", landmark: null },
  { path: "/regime", name: "market regime", kind: "page", criticality: "standard", landmark: /Intraday Market Regime/i },
  { path: "/data-integrity", name: "data integrity", kind: "page", criticality: "standard", landmark: /Data Integrity/i },
  { path: "/framing-brief", name: "framing brief", kind: "page", criticality: "standard", landmark: /Morning Framing Brief/i },
  { path: "/market-brief-public", name: "public market brief", kind: "page", criticality: "standard", landmark: /JARVIS Market Brief/i },
  { path: "/master", name: "master jarvis", kind: "page", criticality: "standard", landmark: /Master Jarvis/i },
  { path: "/master/finances", name: "master finances", kind: "page", criticality: "standard", landmark: /Finances/i },
  { path: "/master/trading", name: "master trading", kind: "page", criticality: "standard", landmark: /Trading/i },
  { path: "/crypto", name: "crypto", kind: "page", criticality: "standard", landmark: null },
  { path: "/signal-outcomes", name: "signal outcomes", kind: "page", criticality: "standard", landmark: /Signal Outcomes/i },
  { path: "/atr-trail", name: "atr trail", kind: "page", criticality: "standard", landmark: /ATR-Trail Strategy/i },
  { path: "/strategy-ledger", name: "strategy ledger", kind: "page", criticality: "standard", landmark: /Strategy Ledger/i },
  { path: "/strategy-c-command", name: "strategy c command", kind: "page", criticality: "standard", landmark: null },
  { path: "/pipeline-board", name: "pipeline board", kind: "page", criticality: "standard", landmark: /Pipeline Board/i },
  { path: "/vault", name: "vault", kind: "page", criticality: "standard", landmark: /Vault/i },

  // ---- research: must carry an exploratory provenance banner ---------------
  { path: "/analysis", name: "analysis", kind: "page", criticality: "research", landmark: /JARVIS TRADER . Analysis/i },
  { path: "/analysis/spx", name: "spx intraday analysis", kind: "page", criticality: "research", landmark: /SPX INTRADAY ANALYSIS/i },
  { path: "/backtest", name: "backtest results", kind: "page", criticality: "research", landmark: /JARVIS TRADER . Backtest Results/i },
  { path: "/strategy-research", name: "strategy research", kind: "page", criticality: "research", landmark: /Strategy Research/i },
  { path: "/research-log", name: "research log", kind: "page", criticality: "research", landmark: /RESEARCH JOURNAL/i },
  { path: "/learning", name: "learning", kind: "page", criticality: "research", landmark: null },
  { path: "/kairos", name: "kairos", kind: "page", criticality: "research", landmark: null },
  { path: "/hidden-pivots", name: "hidden pivots", kind: "page", criticality: "research", landmark: null },
  { path: "/screener", name: "pine screener", kind: "page", criticality: "research", landmark: /Pine Screener/i },
  { path: "/polymarket", name: "polymarket", kind: "page", criticality: "research", landmark: null },
  // The first <h1> here is literally "Signal Unavailable" -- a fallback state, not
  // a page title. Asserting on it would lock in the empty state as expected.
  { path: "/strategy-c", name: "strategy c", kind: "page", criticality: "research", landmark: null },
  { path: "/thinkscript", name: "thinkscript", kind: "page", criticality: "research", landmark: /ThinkScript/i },

  // ---- legacy pages (archived in (legacy) route group, URL-invisible) ------
<<<<<<< HEAD
=======
  { path: "/legacy", name: "legacy index", kind: "page", criticality: "standard", landmark: /Legacy Pages/i },
>>>>>>> origin/master
  { path: "/domflow", name: "domflow legacy", kind: "page", criticality: "research", landmark: /MES DOM \/ Order-Flow/i },
  { path: "/jarvis", name: "jarvis legacy", kind: "page", criticality: "standard", landmark: /JARVIS COMMAND CENTER/i },
  { path: "/journal-review", name: "journal review legacy", kind: "page", criticality: "research", landmark: null },
  { path: "/parallel-paper", name: "parallel paper legacy", kind: "page", criticality: "standard", landmark: /Parallel Paper A\/B Comparison/i },

  // ---- new pages -----------------------------------------------------------
  { path: "/setup-scorecard", name: "setup scorecard", kind: "page", criticality: "standard", landmark: /Setup Scorecard/i },

  // ---- dynamic -------------------------------------------------------------
  { path: "/trades/[id]/review", name: "trade review", kind: "dynamic", criticality: "critical", landmark: null, samplePath: "/trades/1/review" },
];

/** Routes carrying no distinctive landmark yet. This number must only go DOWN.
 *  The manifest test enforces that as a ratchet. */
export const LANDMARK_DEBT = ROUTES.filter(r => r.kind === "page" && r.landmark === null).length;

export const CRITICAL_ROUTES = ROUTES.filter(r => r.criticality === "critical");
export const RESEARCH_ROUTES = ROUTES.filter(r => r.criticality === "research");
