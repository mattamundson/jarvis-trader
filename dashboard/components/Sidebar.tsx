"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Brain,
  ChevronRight,
  Cpu,
  Crosshair,
  Database,
  FileText,
  Flame,
  FlaskConical,
  Gauge,
  Globe,
  Hash,
  HeartPulse,
  History,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  Lightbulb,
  LineChart,
  Menu,
  MessageSquare,
  Moon,
  Package,
  Rss,
  Settings,
  Shield,
  Sliders,
  Star,
  Target,
  TrendingUp,
  Trophy,
  Wallet,
  Waves,
  X,
  Zap,
} from "lucide-react";

// ─── Route definitions ────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

// Orphan audit (Phase 2 IA §6 — P2.6). Every real page.tsx route is now either in
// a nav group below, an intentional redirect stub, a dynamic detail route, or is
// justified link-only here. Routes deliberately NOT surfaced in nav:
//   /jarvis          — pending P2.1 fold into flagship + redirect; not surfaced so
//                      nav doesn't advertise a page about to be dissolved.
//   /journal-review  — link-only by design: reached from /journal ("Review"),
//                      /command-center, and /research-log. Folds into /performance +
//                      /journal Review tab in P2.3; kept out of nav to avoid a 4th
//                      journal-namespace link.
//   /parallel-paper  — ENABLE_PARALLEL_PAPER-gated A/B compare; folds into /paper as
//                      a tab (Phase 2 disposition). Off by default, so not in nav.
//   /trades/[id]/review — dynamic per-trade detail, reached from Trade History/Journal.
//   /trades/journal → /journal, /stats → /performance, /today → /command-center
//                      (/today's KPI strip + system-health checklist folded into the
//                      flagship in P2.1) — intentional redirect stubs.
const NAV_GROUPS: NavGroup[] = [
  {
    title: "Trading",
    items: [
      { label: "Dashboard", href: "/", icon: <LayoutDashboard className="h-3.5 w-3.5" /> },
      { label: "Pending Approvals", href: "/trades/pending-approvals", icon: <Zap className="h-3.5 w-3.5" /> },
      { label: "Trade History", href: "/trades", icon: <History className="h-3.5 w-3.5" /> },
      { label: "Paper Trading", href: "/paper", icon: <Layers className="h-3.5 w-3.5" /> },
      { label: "Watchlist", href: "/watchlist", icon: <Star className="h-3.5 w-3.5" /> },
      { label: "Screener", href: "/screener", icon: <Crosshair className="h-3.5 w-3.5" /> },
    ],
  },
  {
    title: "Analysis",
    items: [
      { label: "Analysis", href: "/analysis", icon: <Brain className="h-3.5 w-3.5" /> },
      { label: "Intraday Regime", href: "/regime", icon: <Flame className="h-3.5 w-3.5" /> },
      { label: "Hidden Pivots", href: "/hidden-pivots", icon: <Target className="h-3.5 w-3.5" /> },
      { label: "Backtest", href: "/backtest", icon: <FlaskConical className="h-3.5 w-3.5" /> },
      { label: "Options Chain", href: "/options", icon: <Hash className="h-3.5 w-3.5" /> },
      { label: "Crypto", href: "/crypto", icon: <Waves className="h-3.5 w-3.5" /> },
      { label: "Polymarket", href: "/polymarket", icon: <Globe className="h-3.5 w-3.5" /> },
      { label: "Kairos", href: "/kairos", icon: <Moon className="h-3.5 w-3.5" /> },
    ],
  },
  {
    title: "Portfolio",
    items: [
      { label: "Portfolio", href: "/portfolio", icon: <Wallet className="h-3.5 w-3.5" /> },
      { label: "Performance", href: "/performance", icon: <TrendingUp className="h-3.5 w-3.5" /> },
      { label: "Journal", href: "/journal", icon: <BookOpen className="h-3.5 w-3.5" /> },
      { label: "Scorecard", href: "/scorecard", icon: <Trophy className="h-3.5 w-3.5" /> },
    ],
  },
  {
    // Four "Strategy*" routes do four unrelated things; grouped + relabeled so
    // each purpose reads at a glance (Phase 2 IA §4). Ledger stays here until
    // P2.3 folds it into /readiness.
    title: "Strategies",
    items: [
      { label: "Strategy C+ (Live)", href: "/strategy-c", icon: <Activity className="h-3.5 w-3.5" /> },
      { label: "Strategy C+ Console", href: "/strategy-c-command", icon: <LayoutGrid className="h-3.5 w-3.5" /> },
      { label: "RL Lab", href: "/strategies", icon: <LineChart className="h-3.5 w-3.5" /> },
      { label: "Strategy Ledger", href: "/strategy-ledger", icon: <FlaskConical className="h-3.5 w-3.5" /> },
      { label: "Edge Research", href: "/strategy-research", icon: <Lightbulb className="h-3.5 w-3.5" /> },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { label: "Command Center", href: "/command-center", icon: <Cpu className="h-3.5 w-3.5" /> },
      { label: "Learning", href: "/learning", icon: <Rss className="h-3.5 w-3.5" /> },
      { label: "Research Log", href: "/research-log", icon: <FileText className="h-3.5 w-3.5" /> },
      { label: "Discord", href: "/discord", icon: <MessageSquare className="h-3.5 w-3.5" /> },
    ],
  },
  {
    title: "System",
    items: [
      { label: "Trust & Reconcile", href: "/trust", icon: <Gauge className="h-3.5 w-3.5" /> },
      { label: "Health", href: "/health", icon: <HeartPulse className="h-3.5 w-3.5" /> },
      { label: "Data Integrity", href: "/data-integrity", icon: <Database className="h-3.5 w-3.5" /> },
      { label: "Config", href: "/config", icon: <Sliders className="h-3.5 w-3.5" /> },
      { label: "Settings", href: "/settings", icon: <Settings className="h-3.5 w-3.5" /> },
      { label: "Validation", href: "/validation", icon: <Shield className="h-3.5 w-3.5" /> },
    ],
  },
];

// ─── Sidebar component ────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  function isActive(href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  }

  const sidebarContent = (
    <nav className="flex flex-col h-full">
      {/* Logo / Title */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-border">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/10 shrink-0">
          <Activity className="h-4 w-4 text-accent" />
        </div>
        <div>
          <p className="font-mono text-xs font-bold text-foreground tracking-widest uppercase leading-none">
            JARVIS
          </p>
          <p className="font-mono text-[9px] text-muted-foreground tracking-wider uppercase leading-none mt-0.5">
            TRADER
          </p>
        </div>
        {/* Mobile close button */}
        <button
          className="ml-auto lg:hidden text-muted-foreground hover:text-foreground"
          onClick={() => setMobileOpen(false)}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Nav groups */}
      <div className="flex-1 overflow-y-auto py-2 scrollbar-none">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-1">
            <p className="px-4 pt-3 pb-1 font-mono text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/60">
              {group.title}
            </p>
            {group.items.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={[
                    "flex items-center gap-2.5 mx-2 px-3 py-2 rounded-md text-xs transition-colors",
                    active
                      ? "bg-accent/10 text-accent font-semibold"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
                  ].join(" ")}
                >
                  <span className={active ? "text-accent" : "text-muted-foreground/70"}>
                    {item.icon}
                  </span>
                  <span className="font-mono tracking-wide">{item.label}</span>
                  {active && (
                    <ChevronRight className="ml-auto h-3 w-3 text-accent/60" />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="border-t border-border">
        {/* Master Jarvis is a separate product on a different backend (:8030), not a
            trading surface. Walled off from the trading nav groups into a single
            de-emphasized portal link (Phase 2 IA §5). */}
        <Link
          href="/master"
          onClick={() => setMobileOpen(false)}
          className={[
            "flex items-center gap-2 mx-2 mt-2 px-3 py-2 rounded-md text-[10px] transition-colors",
            isActive("/master")
              ? "text-accent"
              : "text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/30",
          ].join(" ")}
        >
          <ArrowUpRight className="h-3 w-3" />
          <span className="font-mono tracking-wide uppercase">Personal · Master Jarvis</span>
        </Link>
        <div className="px-4 py-3">
          <p className="font-mono text-[9px] text-muted-foreground/40 tracking-wider uppercase">
            v5 · Paper Mode
          </p>
        </div>
      </div>
    </nav>
  );

  return (
    <>
      {/* Desktop sidebar — always visible */}
      <aside className="hidden lg:flex flex-col w-[220px] shrink-0 h-screen sticky top-0 bg-card border-r border-border overflow-hidden">
        {sidebarContent}
      </aside>

      {/* Mobile hamburger trigger */}
      <button
        className="lg:hidden fixed top-3 left-3 z-50 flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card/95 text-muted-foreground hover:text-foreground shadow-sm"
        onClick={() => setMobileOpen(true)}
        aria-label="Open menu"
      >
        <Menu className="h-4 w-4" />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={[
          "lg:hidden fixed inset-y-0 left-0 z-50 w-[240px] bg-card border-r border-border flex flex-col transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
