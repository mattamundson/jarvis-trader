"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MarketModuleHealth {
  market: string;
  status: string;
  daily_pnl: number;
  open_positions: number;
  message: string;
}

interface PortfolioHealthResponse {
  modules: MarketModuleHealth[];
  count: number;
}

interface MarketHealthGridProps {
  showLinks?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function statusColor(status: string): string {
  if (status === "operational") return "#00ff88";
  if (status === "degraded") return "#ffcc00";
  if (["halted", "offline", "error"].includes(status)) return "#ff4444";
  return "#555555";
}

function statusDotClass(status: string): string {
  if (status === "operational") return "bg-bull";
  if (status === "degraded") return "bg-warn";
  if (["halted", "offline", "error"].includes(status)) return "bg-bear";
  return "bg-muted-foreground/30";
}

const MARKET_LINKS: Record<string, string> = {
  futures: "/",
  options: "/options",
  crypto: "/crypto",
  polymarket: "/polymarket",
};

const MARKET_ORDER = ["futures", "options", "crypto", "polymarket"];

// ── Sub-components ────────────────────────────────────────────────────────────

function PlaceholderCard({ label, href, showLinks }: { label: string; href: string; showLinks: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card/50 p-3 flex flex-col gap-2 min-h-[90px]">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</span>
        <span className="inline-flex rounded-full h-2 w-2 bg-muted-foreground/20" />
      </div>
      <p className="font-mono text-[10px] text-muted-foreground/40 italic">Not registered</p>
      {showLinks && (
        <a href={href} className="mt-auto font-mono text-[10px] text-muted-foreground/40 hover:text-accent transition-colors">
          Details →
        </a>
      )}
    </div>
  );
}

function MarketCard({ module, showLinks }: { module: MarketModuleHealth; showLinks: boolean }) {
  const pnlPositive = module.daily_pnl >= 0;
  const dotClass = statusDotClass(module.status);
  const isOperational = module.status === "operational";
  const href = MARKET_LINKS[module.market] ?? "/portfolio";

  return (
    <div className="rounded-xl border border-border bg-card p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {module.market}
        </span>
        {isOperational ? (
          <span className="relative flex h-2 w-2">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dotClass} opacity-75`} />
            <span className={`relative inline-flex rounded-full h-2 w-2 ${dotClass}`} />
          </span>
        ) : (
          <span className={`inline-flex rounded-full h-2 w-2 ${dotClass}`} />
        )}
      </div>

      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">P&L</span>
        <span
          className="font-mono text-xs font-bold tabular-nums"
          style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
        >
          {pnlPositive ? "+" : ""}${module.daily_pnl.toFixed(2)}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">Positions</span>
        <span className="font-mono text-xs tabular-nums text-foreground">{module.open_positions}</span>
      </div>

      <p
        className="font-mono text-[10px] truncate"
        style={{ color: statusColor(module.status) }}
        title={module.message}
      >
        {module.message.length > 38 ? module.message.slice(0, 37) + "…" : module.message}
      </p>

      {showLinks && (
        <a href={href} className="mt-auto font-mono text-[10px] text-muted-foreground/60 hover:text-accent transition-colors">
          Details →
        </a>
      )}
    </div>
  );
}

// ── Main Export ───────────────────────────────────────────────────────────────

export function MarketHealthGrid({ showLinks = false }: MarketHealthGridProps) {
  const { data } = useSWR<PortfolioHealthResponse>(
    "/portfolio/health",
    fetcher,
    { refreshInterval: 5000, shouldRetryOnError: false }
  );

  const moduleMap: Record<string, MarketModuleHealth> = {};
  for (const m of data?.modules ?? []) {
    moduleMap[m.market] = m;
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
        Market Health
      </p>
      <div className="grid grid-cols-2 gap-3">
        {MARKET_ORDER.map((key) => {
          const mod = moduleMap[key];
          return mod ? (
            <MarketCard key={key} module={mod} showLinks={showLinks} />
          ) : (
            <PlaceholderCard
              key={key}
              label={key}
              href={MARKET_LINKS[key] ?? "/portfolio"}
              showLinks={showLinks}
            />
          );
        })}
      </div>
    </div>
  );
}
