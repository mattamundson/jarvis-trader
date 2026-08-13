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
  ShieldCheck,
  Sliders,
  Radar,
  Star,
  SunMedium,
  Target,
  TrendingUp,
  Trophy,
  Wallet,
  Waves,
  X,
  Zap,
} from "lucide-react";
import {
  DEEP_TOOL_GROUPS,
  PRIMARY_NAV_GROUPS,
  type NavigationGroup,
  type NavigationIcon,
} from "@/lib/navigation";

// ─── Route definitions ────────────────────────────────────────────────────────

const NAV_ICONS: Record<NavigationIcon, React.ReactNode> = {
  activity: <Activity className="h-3.5 w-3.5" />,
  book: <BookOpen className="h-3.5 w-3.5" />,
  brain: <Brain className="h-3.5 w-3.5" />,
  cpu: <Cpu className="h-3.5 w-3.5" />,
  crosshair: <Crosshair className="h-3.5 w-3.5" />,
  database: <Database className="h-3.5 w-3.5" />,
  file: <FileText className="h-3.5 w-3.5" />,
  flame: <Flame className="h-3.5 w-3.5" />,
  flask: <FlaskConical className="h-3.5 w-3.5" />,
  gauge: <Gauge className="h-3.5 w-3.5" />,
  globe: <Globe className="h-3.5 w-3.5" />,
  hash: <Hash className="h-3.5 w-3.5" />,
  health: <HeartPulse className="h-3.5 w-3.5" />,
  history: <History className="h-3.5 w-3.5" />,
  layers: <Layers className="h-3.5 w-3.5" />,
  "layout-dashboard": <LayoutDashboard className="h-3.5 w-3.5" />,
  "layout-grid": <LayoutGrid className="h-3.5 w-3.5" />,
  lightbulb: <Lightbulb className="h-3.5 w-3.5" />,
  "line-chart": <LineChart className="h-3.5 w-3.5" />,
  message: <MessageSquare className="h-3.5 w-3.5" />,
  moon: <Moon className="h-3.5 w-3.5" />,
  radar: <Radar className="h-3.5 w-3.5" />,
  rss: <Rss className="h-3.5 w-3.5" />,
  settings: <Settings className="h-3.5 w-3.5" />,
  shield: <Shield className="h-3.5 w-3.5" />,
  "shield-check": <ShieldCheck className="h-3.5 w-3.5" />,
  sliders: <Sliders className="h-3.5 w-3.5" />,
  star: <Star className="h-3.5 w-3.5" />,
  sun: <SunMedium className="h-3.5 w-3.5" />,
  target: <Target className="h-3.5 w-3.5" />,
  trending: <TrendingUp className="h-3.5 w-3.5" />,
  trophy: <Trophy className="h-3.5 w-3.5" />,
  wallet: <Wallet className="h-3.5 w-3.5" />,
  waves: <Waves className="h-3.5 w-3.5" />,
  zap: <Zap className="h-3.5 w-3.5" />,
};

// ─── Sidebar component ────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [deepToolsOpen, setDeepToolsOpen] = useState(false);

  function isActive(href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  }

  function renderGroups(groups: NavigationGroup[]) {
    return groups.map((group) => (
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
                {NAV_ICONS[item.icon]}
              </span>
              <span
                className={`font-mono tracking-wide ${
                  item.exploratory && !active ? "opacity-70" : ""
                }`}
              >
                {item.label}
              </span>
              {item.exploratory && (
                <FlaskConical
                  className="ml-auto h-3 w-3 text-warn/60 shrink-0"
                  aria-label="Exploratory — not validated"
                />
              )}
              {active && !item.exploratory && (
                <ChevronRight className="ml-auto h-3 w-3 text-accent/60" />
              )}
            </Link>
          );
        })}
      </div>
    ));
  }

  const deepRouteActive = DEEP_TOOL_GROUPS.some((group) =>
    group.items.some((item) => isActive(item.href)),
  );

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
        {renderGroups(PRIMARY_NAV_GROUPS)}
        <details
          className="mt-2 border-t border-border/60"
          open={deepRouteActive || deepToolsOpen}
          onToggle={(event) => setDeepToolsOpen(event.currentTarget.open)}
        >
          <summary className="cursor-pointer select-none px-4 py-3 font-mono text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground hover:text-foreground">
            Deep tools
          </summary>
          {renderGroups(DEEP_TOOL_GROUPS)}
        </details>
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
