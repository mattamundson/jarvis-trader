"use client";

import useSWR from "swr";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";
import { Activity } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface PolymarketModuleStatus {
  status: "disabled" | "connected" | "error";
  message: string;
  daily_pnl: number;
  open_positions: number;
  regulatory_note?: string;
}

interface PolymarketMarket {
  token_id: string;
  question: string;
  yes_price?: number;
  no_price?: number;
  volume_24h?: number;
}

interface PolymarketMarketsResponse {
  markets: PolymarketMarket[];
  count: number;
  error?: string;
}

interface PolymarketOpportunity {
  token_id: string;
  question: string;
  yes_price?: number;
  no_price?: number;
  spread?: number;
  volume_24h?: number;
  type?: string;
  confidence?: number;
}

interface PolymarketScanResponse {
  opportunities: PolymarketOpportunity[];
  count: number;
  error?: string;
}

interface PolymarketPnLResponse {
  daily_pnl: number;
  target: number;
  progress_pct: number;
  status: string;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PolymarketPage() {
  const { data: status } = useSWR<PolymarketModuleStatus>("/polymarket/status", fetcher, {
    refreshInterval: REFRESH_MS,
  });
  const { data: markets } = useSWR<PolymarketMarketsResponse>("/polymarket/markets", fetcher, {
    refreshInterval: 30_000,
  });
  const { data: scan } = useSWR<PolymarketScanResponse>("/polymarket/scan", fetcher, {
    refreshInterval: 30_000,
  });
  const { data: pnl } = useSWR<PolymarketPnLResponse>("/polymarket/pnl", fetcher, {
    refreshInterval: REFRESH_MS,
  });

  // Treat loading state (status === undefined) as disabled to avoid flash of enabled UI
  const isEnabled = status !== undefined && status?.status !== "disabled";
  const pnlPositive = (pnl?.daily_pnl ?? 0) >= 0;

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
              <p className="text-xs text-muted-foreground">Polymarket Prediction Markets</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Home"],
                ["/performance", "Performance"],
                ["/journal", "Journal"],
                ["/portfolio", "Portfolio"],
                ["/options", "Options"],
                ["/crypto", "Crypto"],
                ["/polymarket", "Polymarket"],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className={`text-xs transition-colors ${
                    href === "/polymarket"
                      ? "text-accent font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {status && (
              <>
                <span
                  className="font-mono text-xs font-bold tabular-nums"
                  style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
                >
                  {pnlPositive ? "+" : ""}${(pnl?.daily_pnl ?? 0).toFixed(2)} today
                </span>
                <span
                  className="font-mono text-[10px] px-2 py-0.5 rounded border"
                  style={{
                    borderColor: isEnabled ? "#00ff8844" : "#55555544",
                    color: isEnabled ? "#00ff88" : "#555",
                  }}
                >
                  {isEnabled ? "ENABLED" : "DISABLED"}
                </span>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <ExploratoryBanner what="Polymarket scanning is a research module" />
        {/* Regulatory disclaimer banner */}
        <div className="rounded-xl border border-warn/30 bg-warn/5 p-4 space-y-2">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-warn">
            Regulatory Notice
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            Polymarket has U.S. regulatory restrictions (CFTC settled 2022). Module disabled by default.
            U.S. persons may not legally trade on Polymarket. Consider{" "}
            <span className="text-accent">Kalshi</span> (CFTC-regulated prediction market) as a compliant alternative.
          </p>
        </div>

        {/* Status + P&L cards */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Module status */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Module Status
            </p>
            {status ? (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Status</span>
                  <span style={{ color: isEnabled ? "#00ff88" : "#ff4444" }}>
                    {isEnabled ? "Connected" : "Disabled"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Open Positions</span>
                  <span className="tabular-nums">{status.open_positions ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Daily P&L</span>
                  <span
                    style={{
                      color: (status.daily_pnl ?? 0) >= 0 ? "#00ff88" : "#ff4444",
                    }}
                  >
                    {(status.daily_pnl ?? 0) >= 0 ? "+" : ""}${(status.daily_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 italic">Engine offline</p>
            )}
          </div>

          {/* P&L Progress */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Daily Target
            </p>
            {pnl ? (
              <div className="space-y-3">
                <div className="flex items-baseline gap-2">
                  <span
                    className="font-mono text-2xl font-bold tabular-nums"
                    style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
                  >
                    {pnlPositive ? "+" : ""}${(pnl.daily_pnl ?? 0).toFixed(2)}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    / ${(pnl.target ?? 125).toFixed(2)}
                  </span>
                </div>
                <div className="w-full bg-muted/30 rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-accent h-full transition-all"
                    style={{
                      width: `${Math.min(100, (pnl.progress_pct ?? 0))}%`,
                    }}
                  />
                </div>
                <div className="font-mono text-[10px] text-muted-foreground text-right">
                  {(pnl.progress_pct ?? 0).toFixed(1)}% of target
                </div>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 italic">Loading...</p>
            )}
          </div>

          {/* Info card */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Information
            </p>
            <div className="space-y-2 font-mono text-[10px] text-muted-foreground leading-relaxed">
              <p>Polymarket: Peer-to-peer prediction market platform.</p>
              <p>
                Currently in <span style={{ color: "#ffcc00" }}>paper mode</span> only.
              </p>
              <p>Set POLYMARKET_ENABLED=true in .env to activate trading.</p>
            </div>
          </div>
        </div>

        {/* Active positions */}
        {isEnabled && (
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Active Positions
            </p>
            {(status?.open_positions ?? 0) > 0 ? (
              <div className="font-mono text-xs">
                <p className="text-muted-foreground/50 text-center py-6">No position details available</p>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-6">
                No active positions
              </p>
            )}
          </div>
        )}

        {/* Opportunities / Scan Results */}
        {isEnabled && (
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Scan Results
            </p>
            {!scan?.opportunities?.length ? (
              <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-6">
                No opportunities found — run a scan or wait for the next scheduled scan
              </p>
            ) : (
              <div className="font-mono text-xs overflow-x-auto">
                <div className="grid grid-cols-5 gap-2 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <span className="col-span-2">Question</span>
                  <span className="text-right">Spread</span>
                  <span className="text-right">Volume 24h</span>
                  <span className="text-right">Confidence</span>
                </div>
                {scan.opportunities.slice(0, 10).map((opp, i) => (
                  <div key={i} className="grid grid-cols-5 gap-2 py-2 border-b border-border/40 items-center">
                    <span className="col-span-2 text-foreground/80 truncate text-[10px]">
                      {(opp.question ?? "—").substring(0, 40)}...
                    </span>
                    <span className="text-right tabular-nums text-foreground/70">
                      {opp.spread ? `${(opp.spread * 100).toFixed(1)}%` : "—"}
                    </span>
                    <span className="text-right tabular-nums text-foreground/70">
                      {opp.volume_24h ? `$${(opp.volume_24h / 1000).toFixed(0)}k` : "—"}
                    </span>
                    <span
                      className="text-right tabular-nums font-semibold"
                      style={{ color: (opp.confidence ?? 0) > 0.7 ? "#00ff88" : "#ffcc00" }}
                    >
                      {opp.confidence ? `${(opp.confidence * 100).toFixed(0)}%` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Available markets list */}
        {isEnabled && (
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Available Markets ({markets?.count ?? 0})
            </p>
            {!markets?.markets?.length ? (
              <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-6">
                Loading markets...
              </p>
            ) : (
              <div className="font-mono text-xs">
                <div className="grid grid-cols-4 gap-2 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <span className="col-span-2">Question</span>
                  <span className="text-right">Yes Price</span>
                  <span className="text-right">No Price</span>
                </div>
                {markets.markets.slice(0, 20).map((market, i) => (
                  <div key={i} className="grid grid-cols-4 gap-2 py-2 border-b border-border/40 items-center">
                    <span className="col-span-2 text-foreground/80 truncate text-[10px]">
                      {(market.question ?? "—").substring(0, 40)}...
                    </span>
                    <span className="text-right tabular-nums text-foreground/70">
                      {market.yes_price ? `$${market.yes_price.toFixed(2)}` : "—"}
                    </span>
                    <span className="text-right tabular-nums text-foreground/70">
                      {market.no_price ? `$${market.no_price.toFixed(2)}` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Disabled state info */}
        {!isEnabled && (
          <div className="rounded-xl border border-warn/30 bg-warn/5 p-4 space-y-2">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-warn">
              Module Disabled
            </p>
            <p className="font-mono text-xs text-muted-foreground">
              To enable Polymarket trading, set <code className="text-warn">POLYMARKET_ENABLED=true</code> in your{" "}
              <code className="text-warn">.env</code> file and restart the engine.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
