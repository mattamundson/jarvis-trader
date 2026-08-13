export type RouteOwner =
  | "operate"
  | "system"
  | "analyze"
  | "validate"
  | "admin"
  | "research";

export type NavigationIcon =
  | "activity"
  | "book"
  | "brain"
  | "cpu"
  | "crosshair"
  | "database"
  | "file"
  | "flame"
  | "flask"
  | "gauge"
  | "globe"
  | "hash"
  | "health"
  | "history"
  | "layers"
  | "layout-dashboard"
  | "layout-grid"
  | "lightbulb"
  | "line-chart"
  | "message"
  | "moon"
  | "radar"
  | "rss"
  | "settings"
  | "shield"
  | "shield-check"
  | "sliders"
  | "star"
  | "sun"
  | "target"
  | "trending"
  | "trophy"
  | "wallet"
  | "waves"
  | "zap";

export interface NavigationItem {
  label: string;
  href: string;
  icon: NavigationIcon;
  exploratory?: boolean;
}

export interface NavigationGroup {
  title: string;
  items: NavigationItem[];
}

export const PRIMARY_NAV_GROUPS: NavigationGroup[] = [
  {
    title: "Operate",
    items: [
      { label: "Command Center", href: "/command-center", icon: "cpu" },
      { label: "Today at a Glance", href: "/today", icon: "sun" },
      { label: "Pending Approvals", href: "/trades/pending-approvals", icon: "zap" },
      { label: "Paper Trading", href: "/paper", icon: "layers" },
    ],
  },
  {
    title: "Analyze",
    items: [
      { label: "Watchlist", href: "/watchlist", icon: "star" },
      { label: "Signals", href: "/signals", icon: "radar" },
      { label: "Analysis", href: "/analysis", icon: "brain" },
    ],
  },
  {
    title: "Validate",
    items: [
      { label: "Validation", href: "/validation", icon: "shield" },
      { label: "Performance", href: "/performance", icon: "trending" },
      { label: "Trading Eligibility", href: "/trading-eligibility", icon: "shield-check" },
    ],
  },
  {
    title: "System",
    items: [
      { label: "Mission Control", href: "/mission-control", icon: "activity" },
      { label: "Settings", href: "/settings", icon: "settings" },
    ],
  },
];

export const DEEP_TOOL_GROUPS: NavigationGroup[] = [
  {
    title: "Trading tools",
    items: [
      { label: "Dashboard", href: "/", icon: "layout-dashboard" },
      { label: "Trade History", href: "/trades", icon: "history" },
      { label: "Screener", href: "/screener", icon: "crosshair" },
    ],
  },
  {
    title: "Analysis tools",
    items: [
      { label: "Intraday Regime", href: "/regime", icon: "flame" },
      { label: "Hidden Pivots", href: "/hidden-pivots", icon: "target", exploratory: true },
      { label: "Backtest", href: "/backtest", icon: "flask" },
      { label: "Signal Outcomes", href: "/signal-outcomes", icon: "crosshair" },
      { label: "ATR-Trail Viz", href: "/atr-trail", icon: "line-chart" },
      { label: "Options Chain", href: "/options", icon: "hash" },
      { label: "Crypto", href: "/crypto", icon: "waves" },
      { label: "Polymarket", href: "/polymarket", icon: "globe", exploratory: true },
      { label: "Kairos", href: "/kairos", icon: "moon", exploratory: true },
    ],
  },
  {
    title: "Portfolio tools",
    items: [
      { label: "Portfolio", href: "/portfolio", icon: "wallet" },
      { label: "Journal", href: "/journal", icon: "book" },
      { label: "Scorecard", href: "/scorecard", icon: "trophy" },
    ],
  },
  {
    title: "Strategy labs",
    items: [
      { label: "Strategy C+ Signal", href: "/strategy-c", icon: "activity" },
      { label: "Strategy C+ Console", href: "/strategy-c-command", icon: "layout-grid" },
      { label: "RL Lab", href: "/strategies", icon: "line-chart", exploratory: true },
      { label: "Strategy Ledger", href: "/strategy-ledger", icon: "flask" },
      { label: "Edge Research", href: "/strategy-research", icon: "lightbulb", exploratory: true },
    ],
  },
  {
    title: "Intelligence tools",
    items: [
      { label: "Learning", href: "/learning", icon: "rss" },
      { label: "Research Log", href: "/research-log", icon: "file" },
      { label: "Discord", href: "/discord", icon: "message" },
      { label: "Framing Brief", href: "/framing-brief", icon: "sun" },
    ],
  },
  {
    title: "System diagnostics",
    items: [
      { label: "Trust Pane", href: "/trust-pane", icon: "gauge" },
      { label: "Health", href: "/health", icon: "health" },
      { label: "Data Integrity", href: "/data-integrity", icon: "database" },
      { label: "Config", href: "/config", icon: "sliders" },
    ],
  },
];

const OWNER_PREFIXES: Array<[string, RouteOwner]> = [
  ["/trades/pending-approvals", "operate"],
  ["/trades", "operate"],
  ["/command-center", "operate"],
  ["/today", "operate"],
  ["/paper", "operate"],
  ["/mission-control", "system"],
  ["/data-integrity", "system"],
  ["/trust-pane", "system"],
  ["/health", "system"],
  ["/config", "system"],
  ["/settings", "system"],
  ["/trading-eligibility", "validate"],
  ["/signal-outcomes", "validate"],
  ["/strategy-ledger", "validate"],
  ["/performance", "validate"],
  ["/validation", "validate"],
  ["/portfolio", "validate"],
  ["/scorecard", "validate"],
  ["/journal", "validate"],
  ["/backtest", "validate"],
  ["/hidden-pivots", "research"],
  ["/strategy-research", "research"],
  ["/strategy-c-command", "research"],
  ["/strategy-c", "research"],
  ["/research-log", "research"],
  ["/polymarket", "research"],
  ["/strategies", "research"],
  ["/atr-trail", "research"],
  ["/learning", "research"],
  ["/discord", "research"],
  ["/kairos", "research"],
  ["/master", "admin"],
  ["/framing-brief", "analyze"],
  ["/watchlist", "analyze"],
  ["/screener", "analyze"],
  ["/analysis", "analyze"],
  ["/signals", "analyze"],
  ["/regime", "analyze"],
  ["/options", "analyze"],
  ["/crypto", "analyze"],
];

export function routeOwner(pathname: string): RouteOwner {
  const path = pathname.split(/[?#]/, 1)[0].replace(/\/$/, "") || "/";
  if (path === "/") return "operate";

  return (
    OWNER_PREFIXES.find(
      ([prefix]) => path === prefix || path.startsWith(`${prefix}/`),
    )?.[1] ?? "research"
  );
}
