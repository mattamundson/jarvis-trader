"use client";

import useSWR from "swr";
import { Activity, TrendingUp, TrendingDown, Circle, AlertCircle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface MarketSummary {
  daily_pnl: number;
  open_positions: number;
  status: string;
  message?: string;
}

interface PortfolioSummary {
  total_daily_pnl: number;
  daily_target: number;
  target_progress_pct: number;
  markets: Record<string, MarketSummary>;
  message?: string;
}

interface ModuleHealth {
  market: string;
  status: string;
  message: string;
  daily_pnl: number;
  open_positions: number;
}

interface PortfolioHealth {
  modules: ModuleHealth[];
  count: number;
}

interface MarketCapital {
  capital: number;
  daily_target: number;
}

interface CapitalAllocation {
  markets: Record<string, MarketCapital>;
  total_capital: number;
  daily_target: number;
  enabled_markets: string[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const MARKET_TEXT_CLASSES: Record<string, string> = {
  futures: "text-[#00ff88]",
  options: "text-[#00d4ff]",
  crypto: "text-[#ff9500]",
  polymarket: "text-[#ff6bff]",
};
const MARKET_BG_CLASSES: Record<string, string> = {
  futures: "bg-[#00ff88]",
  options: "bg-[#00d4ff]",
  crypto: "bg-[#ff9500]",
  polymarket: "bg-[#ff6bff]",
};
const MARKET_ORDER = ["futures", "options", "crypto", "polymarket"];

function marketTextClass(market: string) {
  return MARKET_TEXT_CLASSES[market] ?? "text-[#888]";
}
function marketBgClass(market: string) {
  return MARKET_BG_CLASSES[market] ?? "bg-[#888]";
}

function statusDotBgClass(status: string) {
  return status === "operational" ? "bg-[#00ff88]"
    : status === "degraded" ? "bg-[#ffcc00]"
    : ["halted", "offline", "error"].includes(status) ? "bg-[#ff4444]"
    : "bg-[#555]";
}

function statusDot(status: string) {
  const bgClass = statusDotBgClass(status);

  if (status === "operational") {
    return (
      <span className="relative flex h-2 w-2">
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${bgClass}`} />
        <span className={`relative inline-flex rounded-full h-2 w-2 ${bgClass}`} />
      </span>
    );
  }
  return <span className={`inline-flex rounded-full h-2 w-2 ${bgClass}`} />;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function DailyTargetProgress({ total, target }: { total: number; target: number }) {
  const pct = Math.min(100, Math.max(0, target > 0 ? (total / target) * 100 : 0));
  const isPositive = total >= 0;
  const barTextClass = pct >= 100 ? "text-[#00ff88]" : pct >= 50 ? "text-[#ffcc00]" : isPositive ? "text-[#00d4ff]" : "text-[#ff4444]";
  const barBgClass = pct >= 100 ? "bg-[#00ff88]" : pct >= 50 ? "bg-[#ffcc00]" : isPositive ? "bg-[#00d4ff]" : "bg-[#ff4444]";

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Daily Target Progress
        </p>
        <span className="font-mono text-[10px] text-muted-foreground">
          ${target.toFixed(0)}/day goal
        </span>
      </div>

      <div className="flex items-end gap-3">
        <span className={`font-mono text-3xl font-bold tabular-nums leading-none ${barTextClass}`}>
          {isPositive ? "+" : ""}${total.toFixed(2)}
        </span>
        <span className={`font-mono text-lg font-semibold tabular-nums mb-0.5 ${barTextClass}`}>
          {pct.toFixed(1)}%
        </span>
      </div>

      <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barBgClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="font-mono text-[10px] text-muted-foreground">
        {pct >= 100
          ? "✅ Daily target reached"
          : pct >= 50
          ? `${(target - total).toFixed(2)} remaining to hit target`
          : isPositive
          ? `${(target - total).toFixed(2)} remaining — keep going`
          : "Down today — risk controls active"}
      </p>
    </div>
  );
}

function MarketHealthCard({ market, mod, capital }: {
  market: string;
  mod?: ModuleHealth;
  capital?: MarketCapital;
}) {
  const textClass = marketTextClass(market);
  const bgClass = marketBgClass(market);
  const href = market === "futures" ? "/" : `/${market}`;

  if (!mod) {
    return (
      <div className="rounded-xl border border-border bg-card/50 p-4 space-y-2">
        <div className="flex items-center justify-between">
          <span className={`font-mono text-[10px] font-bold uppercase tracking-wider ${textClass}`}>
            {market}
          </span>
          <span className="inline-flex rounded-full h-2 w-2 bg-muted-foreground/20" />
        </div>
        <p className="font-mono text-[10px] text-muted-foreground/40 italic">Not registered</p>
      </div>
    );
  }

  const pnlPositive = mod.daily_pnl >= 0;

  return (
    <a href={href} className="block rounded-xl border border-border bg-card p-4 space-y-3 hover:border-accent/50 transition-colors">
      <div className="flex items-center justify-between">
        <span className={`font-mono text-[10px] font-bold uppercase tracking-wider ${textClass}`}>
          {market}
        </span>
        {statusDot(mod.status)}
      </div>

      <div>
        <span className={`font-mono text-xl font-bold tabular-nums ${pnlPositive ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
          {pnlPositive ? "+" : ""}${mod.daily_pnl.toFixed(2)}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground ml-1">today</span>
      </div>

      <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
        <span>{mod.open_positions} open positions</span>
        {capital && <span>${capital.capital.toLocaleString()} capital</span>}
      </div>

      <p className={`font-mono text-[10px] truncate ${mod.status === "operational" ? "text-[#00ff88]" : "text-[#ffcc00]"}`}>
        {mod.message}
      </p>

      {capital && (
        <div className="space-y-1">
          <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
            <span>Daily target</span>
            <span>${capital.daily_target}/day</span>
          </div>
          <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full ${bgClass}`}
              style={{
                width: `${Math.min(100, capital.daily_target > 0 ? (mod.daily_pnl / capital.daily_target) * 100 : 0)}%`,
              }}
            />
          </div>
        </div>
      )}
    </a>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { data: summary } = useSWR<PortfolioSummary>("/portfolio/summary", fetcher, { refreshInterval: REFRESH_MS });
  const { data: health } = useSWR<PortfolioHealth>("/portfolio/health", fetcher, { refreshInterval: REFRESH_MS });
  const { data: capital, error: capitalError } = useSWR<CapitalAllocation>("/portfolio/capital", fetcher, { refreshInterval: 30_000 });

  const moduleMap: Record<string, ModuleHealth> = {};
  for (const m of health?.modules ?? []) moduleMap[m.market] = m;

  const total = summary?.total_daily_pnl ?? 0;
  const target = summary?.daily_target ?? 500;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">Multi-Market Portfolio</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Home"], ["/analysis", "Analysis"], ["/backtest", "Backtest"],
                ["/performance", "Performance"], ["/validation", "Validation"],
                ["/journal", "Journal"], ["/paper", "Paper"], ["/watchlist", "Watchlist"],
                ["/scorecard", "Scorecard"], ["/settings", "Settings"], ["/health", "Health"],
                ["/options", "Options"], ["/crypto", "Crypto"], ["/discord", "Discord Intel"], ["/learning", "Learning"],
              ].map(([href, label]) => (
                <a key={href} href={href} className={`text-xs transition-colors ${href === "/portfolio" ? "text-accent font-semibold" : "text-muted-foreground hover:text-foreground"}`}>
                  {label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted-foreground">
              {health?.count ?? 0} modules active
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Daily target progress */}
        <DailyTargetProgress total={total} target={target} />

        {/* Market health grid */}
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
            Market Modules
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {MARKET_ORDER.map((market) => (
              <MarketHealthCard
                key={market}
                market={market}
                mod={moduleMap[market]}
                capital={capital?.markets?.[market]}
              />
            ))}
          </div>
        </div>

        {/* P&L breakdown table */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
            P&L Breakdown
          </p>
          <div className="font-mono text-xs">
            <div className="grid grid-cols-5 gap-2 pb-2 mb-2 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
              <span>Market</span>
              <span className="text-center">Status</span>
              <span className="text-right">Daily P&L</span>
              <span className="text-right">Capital</span>
              <span className="text-right">Positions</span>
            </div>

            {MARKET_ORDER.map((market) => {
              const mod = moduleMap[market];
              const cap = capital?.markets?.[market];
              const textClass = marketTextClass(market);
              if (!mod) {
                return (
                  <div key={market} className="grid grid-cols-5 gap-2 py-2 border-b border-border/50 text-muted-foreground/40">
                    <span className={`uppercase ${textClass}`}>{market}</span>
                    <span className="text-center">—</span>
                    <span className="text-right">—</span>
                    <span className="text-right">{cap ? `$${cap.capital.toLocaleString()}` : "—"}</span>
                    <span className="text-right">—</span>
                  </div>
                );
              }
              return (
                <div key={market} className="grid grid-cols-5 gap-2 py-2 border-b border-border/50">
                  <span className={`font-semibold uppercase ${textClass}`}>{market}</span>
                  <span className={`text-center ${mod.status === "operational" ? "text-[#00ff88]" : "text-[#ffcc00]"}`}>
                    {mod.status}
                  </span>
                  <span className={`text-right tabular-nums font-semibold ${mod.daily_pnl >= 0 ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
                    {mod.daily_pnl >= 0 ? "+" : ""}${mod.daily_pnl.toFixed(2)}
                  </span>
                  <span className="text-right tabular-nums text-foreground/70">
                    {cap ? `$${cap.capital.toLocaleString()}` : "—"}
                  </span>
                  <span className="text-right tabular-nums text-foreground">{mod.open_positions}</span>
                </div>
              );
            })}

            {/* Totals row */}
            <div className="grid grid-cols-5 gap-2 py-2 pt-3 text-[11px] font-bold">
              <span className="text-muted-foreground uppercase tracking-wider">Total</span>
              <span />
              <span className={`text-right tabular-nums ${total >= 0 ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
                {total >= 0 ? "+" : ""}${total.toFixed(2)}
              </span>
              <span className="text-right tabular-nums text-foreground/70">
                {capital ? `$${capital.total_capital.toLocaleString()}` : "—"}
              </span>
              <span className="text-right tabular-nums">
                {health?.modules.reduce((s, m) => s + m.open_positions, 0) ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Capital allocation */}
        {capitalError && !capital ? (
          <div className="rounded-xl border border-border bg-muted/40 p-4 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <p className="font-mono text-[11px] font-semibold text-amber-500">Capital Allocation — unavailable</p>
              <p className="font-mono text-[10px] text-muted-foreground mt-0.5">
                Endpoint <code className="bg-muted px-1 rounded">/portfolio/capital</code> is not available on the engine. Capital figures will not be shown.
              </p>
            </div>
          </div>
        ) : capital ? (
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Capital Allocation — ${capital.total_capital.toLocaleString()} total
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {MARKET_ORDER.map((market) => {
                const cap = capital.markets[market];
                if (!cap) return null;
                const textClass = marketTextClass(market);
                const bgClass = marketBgClass(market);
                const sharePct = capital.total_capital > 0 ? (cap.capital / capital.total_capital) * 100 : 0;
                const enabled = capital.enabled_markets.includes(market);
                return (
                  <div key={market} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className={`font-mono text-[10px] uppercase tracking-wider ${textClass}`}>
                        {market}
                      </span>
                      {!enabled && (
                        <span className="font-mono text-[9px] text-muted-foreground/50 border border-border rounded px-1">
                          disabled
                        </span>
                      )}
                    </div>
                    <p className={`font-mono text-sm font-bold tabular-nums ${textClass}`}>
                      ${cap.capital.toLocaleString()}
                    </p>
                    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full ${bgClass} ${enabled ? "opacity-100" : "opacity-30"}`}
                        style={{ width: `${sharePct}%` }}
                      />
                    </div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {sharePct.toFixed(0)}% share · ${cap.daily_target}/day target
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
