"use client";

import useSWR from "swr";
import { Activity, TrendingUp, TrendingDown, Circle } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { OfflineFallback } from "@/components/OfflineFallback";
import React, { useEffect, useState } from "react";

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

const MARKET_COLORS: Record<string, string> = {
  futures: "#00ff88",
  options: "#00d4ff",
  crypto: "#ff9500",
  polymarket: "#ff6bff",
};
const MARKET_ORDER = ["futures", "options", "crypto", "polymarket"];

function statusDot(status: string) {
  const color =
    status === "operational" ? "#00ff88"
    : status === "degraded" ? "#ffcc00"
    : ["halted", "offline", "error"].includes(status) ? "#ff4444"
    : "#555";

  if (status === "operational") {
    return (
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ backgroundColor: color }} />
        <span className="relative inline-flex rounded-full h-2 w-2" style={{ backgroundColor: color }} />
      </span>
    );
  }
  return <span className="inline-flex rounded-full h-2 w-2" style={{ backgroundColor: color }} />;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function DailyTargetProgress({ total, target }: { total: number; target: number }) {
  const pct = Math.min(100, Math.max(0, target > 0 ? (total / target) * 100 : 0));
  const isPositive = total >= 0;
  const barColor = pct >= 100 ? "#00ff88" : pct >= 50 ? "#ffcc00" : isPositive ? "#00d4ff" : "#ff4444";

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
        <span
          className="font-mono text-3xl font-bold tabular-nums leading-none"
          style={{ color: barColor }}
        >
          {isPositive ? "+" : ""}${total.toFixed(2)}
        </span>
        <span
          className="font-mono text-lg font-semibold tabular-nums mb-0.5"
          style={{ color: barColor }}
        >
          {pct.toFixed(1)}%
        </span>
      </div>

      <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
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
  const color = MARKET_COLORS[market] ?? "#888";
  const href = market === "futures" ? "/" : `/${market}`;

  if (!mod) {
    return (
      <div className="rounded-xl border border-border bg-card/50 p-4 space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color }}>
            {market}
          </span>
          <span className="inline-flex rounded-full h-2 w-2 bg-muted-foreground/20" />
        </div>
        <p className="font-mono text-[10px] italic" style={{ color: "#333" }} title="Module not active — engine not running or market disabled in config">Not registered</p>
      </div>
    );
  }

  const pnlPositive = mod.daily_pnl >= 0;

  return (
    <a href={href} className="block rounded-xl border border-border bg-card p-4 space-y-3 hover:border-accent/50 transition-colors">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color }}>
          {market}
        </span>
        {statusDot(mod.status)}
      </div>

      <div>
        <span
          className="font-mono text-xl font-bold tabular-nums"
          style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
        >
          {pnlPositive ? "+" : ""}${mod.daily_pnl.toFixed(2)}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground ml-1">today</span>
      </div>

      <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
        <span>{mod.open_positions} open positions</span>
        {capital && <span>${capital.capital.toLocaleString()} capital</span>}
      </div>

      <p className="font-mono text-[10px] truncate" style={{ color: mod.status === "operational" ? "#00ff88" : "#ffcc00" }}>
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
              className="h-full rounded-full"
              style={{
                width: `${Math.min(100, capital.daily_target > 0 ? (mod.daily_pnl / capital.daily_target) * 100 : 0)}%`,
                backgroundColor: color,
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
  const { data: summary, error: summaryError } = useSWR<PortfolioSummary>("/portfolio/summary", fetcher, { refreshInterval: REFRESH_MS });
  const { data: health } = useSWR<PortfolioHealth>("/portfolio/health", fetcher, { refreshInterval: REFRESH_MS });
  const { data: capital } = useSWR<CapitalAllocation>("/portfolio/capital", fetcher, { refreshInterval: 30_000 });

  const engineOffline = !!summaryError;

  // Persist last-known portfolio data to localStorage
  useEffect(() => {
    if (summary) {
      try {
        localStorage.setItem('jarvis:portfolio:last_known', JSON.stringify({
          data: summary,
          timestamp: new Date().toISOString()
        }));
      } catch {}
    }
  }, [summary]);

  // Read stale data when offline
  const [staleData, setStaleData] = useState<{data: PortfolioSummary, timestamp: string} | null>(null);
  useEffect(() => {
    try {
      const raw = localStorage.getItem('jarvis:portfolio:last_known');
      if (raw) setStaleData(JSON.parse(raw));
    } catch {}
  }, []);

  const displaySummary = summary ?? staleData?.data ?? null;
  const isStale = !summary && !!staleData;

  const moduleMap: Record<string, ModuleHealth> = {};
  for (const m of health?.modules ?? []) moduleMap[m.market] = m;

  const total = displaySummary?.total_daily_pnl ?? 0;
  const target = displaySummary?.daily_target ?? 500;

  return (
    <div className="min-h-screen bg-background">
      {engineOffline && (
        <div className="px-6 py-2 flex items-center gap-2 border-b border-[#1a1a2e]" style={{ backgroundColor: "#0d0d1a" }}>
          <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: "#555" }} />
          <OfflineFallback variant="inline" message="Engine offline — showing last known state" />
        </div>
      )}
      {isStale && staleData && (
        <div className="px-6 py-1 flex items-center gap-2" style={{ backgroundColor: "#0a0a0a" }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#ffaa00" }} />
          <span className="text-[10px] font-mono" style={{ color: "#ffaa00" }}>
            Showing cached data from {new Date(staleData.timestamp).toLocaleTimeString()}
          </span>
        </div>
      )}
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Daily target progress */}
        {(displaySummary || engineOffline === false) ? (
          <DailyTargetProgress total={total} target={target} />
        ) : (
          <div className="rounded-widget border p-4" style={{ backgroundColor: "#0a0a0a", borderColor: "#1a1a2e" }}>
            <p className="text-[10px] font-mono uppercase tracking-widest mb-2" style={{ color: "#555" }}>Daily Target</p>
            <p className="text-xs font-mono" style={{ color: "#333" }}>No trading data yet — start the engine to begin tracking P&amp;L</p>
          </div>
        )}

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
              const color = MARKET_COLORS[market] ?? "#888";
              if (!mod) {
                return (
                  <div key={market} className="grid grid-cols-5 gap-2 py-2 border-b border-border/50 text-muted-foreground/40">
                    <span style={{ color }} className="uppercase">{market}</span>
                    <span className="text-center">—</span>
                    <span className="text-right">—</span>
                    <span className="text-right">{cap ? `$${cap.capital.toLocaleString()}` : "—"}</span>
                    <span className="text-right">—</span>
                  </div>
                );
              }
              return (
                <div key={market} className="grid grid-cols-5 gap-2 py-2 border-b border-border/50">
                  <span className="font-semibold uppercase" style={{ color }}>{market}</span>
                  <span className="text-center" style={{ color: mod.status === "operational" ? "#00ff88" : "#ffcc00" }}>
                    {mod.status}
                  </span>
                  <span
                    className="text-right tabular-nums font-semibold"
                    style={{ color: mod.daily_pnl >= 0 ? "#00ff88" : "#ff4444" }}
                  >
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
              <span
                className="text-right tabular-nums"
                style={{ color: total >= 0 ? "#00ff88" : "#ff4444" }}
              >
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
        {capital && (
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Capital Allocation — ${capital.total_capital.toLocaleString()} total
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {MARKET_ORDER.map((market) => {
                const cap = capital.markets[market];
                if (!cap) return null;
                const color = MARKET_COLORS[market] ?? "#888";
                const sharePct = capital.total_capital > 0 ? (cap.capital / capital.total_capital) * 100 : 0;
                const enabled = capital.enabled_markets.includes(market);
                return (
                  <div key={market} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color }}>
                        {market}
                      </span>
                      {!enabled && (
                        <span className="font-mono text-[9px] text-muted-foreground/50 border border-border rounded px-1">
                          disabled
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-sm font-bold tabular-nums" style={{ color }}>
                      ${cap.capital.toLocaleString()}
                    </p>
                    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${sharePct}%`, backgroundColor: color, opacity: enabled ? 1 : 0.3 }}
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
        )}
      </main>
    </div>
  );
}
