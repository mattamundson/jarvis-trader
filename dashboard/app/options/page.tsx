"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Activity, AlertCircle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface OptionsModuleStatus {
  enabled: boolean;
  connected: boolean;
  daily_pnl: number;
  open_positions_count: number;
  vix_regime: string;
  current_strategy: string;
  last_scan_time?: string;
}

interface ScanResult {
  symbol: string;
  strategy_type: string;
  iv_rank: number;
  expiry_date: string;
  estimated_premium: number;
}

interface OptionsScanResponse {
  scan_results: ScanResult[];
  vix_regime: string;
  strategy_selected: string;
}

interface OptionsPosition {
  symbol: string;
  strategy: string;
  entry_price: number;
  current_price: number;
  pnl: number;
  dte: number;
}

interface OptionsPnLResponse {
  daily_pnl: number;
  total_pnl: number;
  open_positions: OptionsPosition[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function vixRegimeColor(regime: string): string {
  if (regime === "low") return "#00ff88";
  if (regime === "normal") return "#00d4ff";
  if (regime === "high") return "#ff4444";
  return "#888";
}

function strategyLabel(strategy: string): string {
  if (strategy === "iron_condor") return "Iron Condor";
  if (strategy === "bull_put_spread") return "Bull Put Spread";
  if (strategy === "bear_call_spread") return "Bear Call Spread";
  if (strategy === "skip") return "SKIP (high VIX)";
  return strategy;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OptionsPage() {
  const { data: status } = useSWR<OptionsModuleStatus>("/options/module/status", fetcher, { refreshInterval: REFRESH_MS, shouldRetryOnError: false });
  const { data: scan, error: scanError } = useSWR<OptionsScanResponse>("/options/module/scan", fetcher, { refreshInterval: POLL_INTERVAL.SLOW, shouldRetryOnError: false });
  const { data: pnlData, error: pnlError } = useSWR<OptionsPnLResponse>("/options/module/pnl", fetcher, { refreshInterval: REFRESH_MS, shouldRetryOnError: false });

  const pnlPositive = (pnlData?.daily_pnl ?? 0) >= 0;

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
              <p className="text-xs text-muted-foreground">Options Automation</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Home"], ["/performance", "Performance"], ["/journal", "Journal"],
                ["/portfolio", "Portfolio"], ["/crypto", "Crypto"], ["/discord", "Discord Intel"], ["/learning", "Learning"], ["/health", "Health"],
              ].map(([href, label]) => (
                <a key={href} href={href} className={`text-xs transition-colors ${href === "/options" ? "text-accent font-semibold" : "text-muted-foreground hover:text-foreground"}`}>
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
                  {pnlPositive ? "+" : ""}${(pnlData?.daily_pnl ?? 0).toFixed(2)} today
                </span>
                <span
                  className="font-mono text-[10px] px-2 py-0.5 rounded border"
                  style={{
                    borderColor: status.enabled ? "#00ff8844" : "#55555544",
                    color: status.enabled ? "#00ff88" : "#555",
                  }}
                >
                  {status.enabled ? "ENABLED" : "DISABLED"}
                </span>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Status + VIX regime */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Module status */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Module Status
            </p>
            {status ? (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Connection</span>
                  <span style={{ color: status.connected ? "#00ff88" : "#ff4444" }}>
                    {status.connected ? "Connected" : "Disconnected"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Open Positions</span>
                  <span className="tabular-nums">{status.open_positions_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Current Strategy</span>
                  <span style={{ color: "#00d4ff" }}>{strategyLabel(status.current_strategy ?? "—")}</span>
                </div>
                {status.last_scan_time && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Last Scan</span>
                    <span className="text-foreground/70 text-[10px]">
                      {new Date(status.last_scan_time).toLocaleTimeString()}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 italic">Engine offline</p>
            )}
          </div>

          {/* VIX regime */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              VIX Regime
            </p>
            <div className="flex flex-col items-center justify-center h-16">
              <span
                className="font-mono text-2xl font-bold uppercase tracking-widest"
                style={{ color: vixRegimeColor(status?.vix_regime ?? scan?.vix_regime ?? "") }}
              >
                {status?.vix_regime?.toUpperCase() ?? scan?.vix_regime?.toUpperCase() ?? "—"}
              </span>
              <p className="font-mono text-[10px] text-muted-foreground mt-1">
                {status?.vix_regime === "low" && "VIX < 15 — Iron condors preferred"}
                {status?.vix_regime === "normal" && "VIX 15-25 — Credit spreads preferred"}
                {status?.vix_regime === "high" && "VIX > 25 — Reducing exposure"}
                {!status?.vix_regime && "Waiting for data…"}
              </p>
            </div>
          </div>

          {/* P&L summary */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              P&L Summary
            </p>
            {pnlError && !pnlData ? (
              <div className="flex items-start gap-2 py-1">
                <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                <p className="font-mono text-[10px] text-muted-foreground">
                  Data unavailable — endpoint{" "}
                  <code className="bg-muted px-1 rounded">/options/module/pnl</code>{" "}
                  not available on engine.
                </p>
              </div>
            ) : (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Daily P&L</span>
                  <span
                    className="tabular-nums font-bold"
                    style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
                  >
                    {pnlPositive ? "+" : ""}${(pnlData?.daily_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Total P&L</span>
                  <span
                    className="tabular-nums"
                    style={{ color: (pnlData?.total_pnl ?? 0) >= 0 ? "#00ff88" : "#ff4444" }}
                  >
                    {(pnlData?.total_pnl ?? 0) >= 0 ? "+" : ""}${(pnlData?.total_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Open Positions</span>
                  <span className="tabular-nums">{pnlData?.open_positions?.length ?? 0}</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Scan results */}
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Latest Scan Results
            </p>
            {scan?.strategy_selected && (
              <span className="font-mono text-[10px] px-2 py-0.5 rounded" style={{ backgroundColor: "#00d4ff15", color: "#00d4ff" }}>
                {strategyLabel(scan.strategy_selected)}
              </span>
            )}
          </div>

          {scanError && !scan ? (
            <div className="flex items-start gap-2 py-4">
              <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
              <p className="font-mono text-[10px] text-muted-foreground">
                Data unavailable — endpoint{" "}
                <code className="bg-muted px-1 rounded">/options/module/scan</code>{" "}
                not available on engine.
              </p>
            </div>
          ) : !scan?.scan_results?.length ? (
            <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-6">
              No scan results — run a scan or wait for the next scheduled scan
            </p>
          ) : (
            <div className="font-mono text-xs">
              <div className="grid grid-cols-5 gap-2 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                <span>Symbol</span>
                <span>Strategy</span>
                <span className="text-right">IV Rank</span>
                <span className="text-right">Expiry</span>
                <span className="text-right">Est. Premium</span>
              </div>
              {scan.scan_results.map((r, i) => (
                <div key={i} className="grid grid-cols-5 gap-2 py-2 border-b border-border/40">
                  <span className="font-semibold text-foreground">{r.symbol}</span>
                  <span style={{ color: "#00d4ff" }}>{strategyLabel(r.strategy_type)}</span>
                  <span className="text-right tabular-nums" style={{ color: r.iv_rank > 50 ? "#00ff88" : "#ffcc00" }}>
                    {r.iv_rank.toFixed(0)}%
                  </span>
                  <span className="text-right text-foreground/70">{r.expiry_date}</span>
                  <span className="text-right tabular-nums text-bull">${r.estimated_premium.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Open positions */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
            Open Positions
          </p>
          {pnlError && !pnlData ? (
            <div className="flex items-start gap-2 py-4">
              <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
              <p className="font-mono text-[10px] text-muted-foreground">
                Data unavailable — endpoint{" "}
                <code className="bg-muted px-1 rounded">/options/module/pnl</code>{" "}
                not available on engine.
              </p>
            </div>
          ) : !pnlData?.open_positions?.length ? (
            <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-6">
              No open positions
            </p>
          ) : (
            <div className="font-mono text-xs">
              <div className="grid grid-cols-6 gap-2 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                <span>Symbol</span>
                <span>Strategy</span>
                <span className="text-right">Entry</span>
                <span className="text-right">Current</span>
                <span className="text-right">P&L</span>
                <span className="text-right">DTE</span>
              </div>
              {pnlData.open_positions.map((pos, i) => {
                const pnlPos = pos.pnl >= 0;
                const dteColor = pos.dte <= 5 ? "#ff4444" : pos.dte <= 21 ? "#ffcc00" : "#00ff88";
                return (
                  <div key={i} className="grid grid-cols-6 gap-2 py-2 border-b border-border/40">
                    <span className="font-semibold">{pos.symbol}</span>
                    <span style={{ color: "#00d4ff" }}>{strategyLabel(pos.strategy)}</span>
                    <span className="text-right tabular-nums text-foreground/70">${pos.entry_price.toFixed(2)}</span>
                    <span className="text-right tabular-nums">${pos.current_price.toFixed(2)}</span>
                    <span className="text-right tabular-nums font-semibold" style={{ color: pnlPos ? "#00ff88" : "#ff4444" }}>
                      {pnlPos ? "+" : ""}${pos.pnl.toFixed(2)}
                    </span>
                    <span className="text-right tabular-nums font-semibold" style={{ color: dteColor }}>
                      {pos.dte}d
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
