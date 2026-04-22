"use client";

import { useState } from "react";
import useSWR from "swr";
import { Activity } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface CryptoStatus {
  enabled: boolean;
  connected: boolean;
  daily_pnl: number;
  open_positions_count: number;
  freqtrade_running: boolean;
  last_sync?: string;
}

interface FreqtradeStatus {
  running: boolean;
  version: string;
  state: string;
  dry_run: boolean;
  bot_name: string;
  open_trade_count: number;
  profit_today_abs: number;
}

interface CryptoPosition {
  pair: string;
  open_date: string;
  stake_amount: number;
  current_rate: number;
  profit_pct: number;
  profit_abs: number;
}

interface CryptoPositions {
  positions: CryptoPosition[];
}

interface CryptoPnL {
  daily_pnl: number;
  total_pnl: number;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CryptoPage() {
  const { data: status, mutate: mutateStatus } = useSWR<CryptoStatus>("/crypto/status", fetcher, { refreshInterval: REFRESH_MS });
  const { data: ftStatus, mutate: mutateFt } = useSWR<FreqtradeStatus>("/crypto/freqtrade/status", fetcher, { refreshInterval: REFRESH_MS });
  const { data: positions } = useSWR<CryptoPositions>("/crypto/positions", fetcher, { refreshInterval: REFRESH_MS });
  const { data: pnl } = useSWR<CryptoPnL>("/crypto/pnl", fetcher, { refreshInterval: REFRESH_MS });

  const [actionLoading, setActionLoading] = useState<"start" | "stop" | null>(null);

  async function controlFreqtrade(action: "start" | "stop") {
    setActionLoading(action);
    try {
      await fetchEngine(`/crypto/freqtrade/${action}`, { method: "POST" });
      setTimeout(() => { mutateStatus(); mutateFt(); }, 1500);
    } catch (e) {
      console.error(e);
    } finally {
      setActionLoading(null);
    }
  }

  const pnlPositive = (pnl?.daily_pnl ?? 0) >= 0;
  const isRunning = ftStatus?.running ?? status?.freqtrade_running ?? false;

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
              <p className="text-xs text-muted-foreground">Crypto — Freqtrade</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Home"], ["/performance", "Performance"], ["/journal", "Journal"],
                ["/portfolio", "Portfolio"], ["/options", "Options"], ["/discord", "Discord Intel"], ["/learning", "Learning"], ["/health", "Health"],
              ].map(([href, label]) => (
                <a key={href} href={href} className={`text-xs transition-colors ${href === "/crypto" ? "text-accent font-semibold" : "text-muted-foreground hover:text-foreground"}`}>
                  {label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="font-mono text-[10px] px-2 py-0.5 rounded border"
              style={{
                borderColor: isRunning ? "#00ff8844" : "#55555544",
                color: isRunning ? "#00ff88" : "#555",
              }}
            >
              {isRunning ? "RUNNING" : "STOPPED"}
            </span>
            {ftStatus?.dry_run && (
              <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-warn/30 text-warn">
                DRY RUN
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Status cards row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Freqtrade status */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Freqtrade Status
            </p>
            {ftStatus ? (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">State</span>
                  <span style={{ color: ftStatus.state === "running" ? "#00ff88" : "#ffcc00" }}>
                    {ftStatus.state?.toUpperCase() ?? "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bot Name</span>
                  <span className="text-foreground/70">{ftStatus.bot_name ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Version</span>
                  <span className="text-foreground/70">{ftStatus.version ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Open Trades</span>
                  <span className="tabular-nums">{ftStatus.open_trade_count ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Today's Profit</span>
                  <span
                    className="tabular-nums font-bold"
                    style={{ color: (ftStatus.profit_today_abs ?? 0) >= 0 ? "#00ff88" : "#ff4444" }}
                  >
                    {(ftStatus.profit_today_abs ?? 0) >= 0 ? "+" : ""}
                    ${(ftStatus.profit_today_abs ?? 0).toFixed(2)}
                  </span>
                </div>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 italic">
                Freqtrade not reachable at localhost:8080
              </p>
            )}

            {/* Controls */}
            <div className="flex gap-2 pt-2">
              <button
                onClick={() => controlFreqtrade("start")}
                disabled={isRunning || actionLoading !== null}
                className="flex-1 rounded-lg py-1.5 text-xs font-semibold font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ backgroundColor: "#00ff8820", color: "#00ff88" }}
              >
                {actionLoading === "start" ? "Starting…" : "Start"}
              </button>
              <button
                onClick={() => controlFreqtrade("stop")}
                disabled={!isRunning || actionLoading !== null}
                className="flex-1 rounded-lg py-1.5 text-xs font-semibold font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ backgroundColor: "#ff444420", color: "#ff4444" }}
              >
                {actionLoading === "stop" ? "Stopping…" : "Stop"}
              </button>
            </div>
          </div>

          {/* P&L summary */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              P&L Summary
            </p>
            <div>
              <span
                className="font-mono text-2xl font-bold tabular-nums"
                style={{ color: pnlPositive ? "#00ff88" : "#ff4444" }}
              >
                {pnlPositive ? "+" : ""}${(pnl?.daily_pnl ?? 0).toFixed(2)}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground ml-2">today</span>
            </div>
            <div className="space-y-2 font-mono text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total P&L</span>
                <span
                  className="tabular-nums"
                  style={{ color: (pnl?.total_pnl ?? 0) >= 0 ? "#00ff88" : "#ff4444" }}
                >
                  {(pnl?.total_pnl ?? 0) >= 0 ? "+" : ""}${(pnl?.total_pnl ?? 0).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Open Positions</span>
                <span className="tabular-nums">{positions?.positions?.length ?? 0}</span>
              </div>
            </div>
          </div>

          {/* Module status */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Module Status
            </p>
            {status ? (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Enabled</span>
                  <span style={{ color: status.enabled ? "#00ff88" : "#555" }}>
                    {status.enabled ? "Yes" : "No"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bridge Connected</span>
                  <span style={{ color: status.connected ? "#00ff88" : "#ff4444" }}>
                    {status.connected ? "Yes" : "No"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Freqtrade Running</span>
                  <span style={{ color: status.freqtrade_running ? "#00ff88" : "#ff4444" }}>
                    {status.freqtrade_running ? "Yes" : "No"}
                  </span>
                </div>
                {status.last_sync && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Last Sync</span>
                    <span className="text-foreground/70 text-[10px]">
                      {new Date(status.last_sync).toLocaleTimeString()}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/50 italic">Engine offline</p>
            )}
          </div>
        </div>

        {/* Open trades table */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
            Open Trades
          </p>
          {!positions?.positions?.length ? (
            <p className="font-mono text-[10px] text-muted-foreground/50 text-center py-8">
              {isRunning ? "No open trades" : "Freqtrade is not running"}
            </p>
          ) : (
            <div className="font-mono text-xs overflow-x-auto">
              <div className="grid grid-cols-6 gap-3 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground min-w-[600px]">
                <span>Pair</span>
                <span>Opened</span>
                <span className="text-right">Stake</span>
                <span className="text-right">Current Rate</span>
                <span className="text-right">Profit %</span>
                <span className="text-right">Profit $</span>
              </div>
              {positions.positions.map((pos, i) => {
                const profitPos = pos.profit_pct >= 0;
                return (
                  <div key={i} className="grid grid-cols-6 gap-3 py-2 border-b border-border/40 min-w-[600px]">
                    <span className="font-semibold" style={{ color: "#ff9500" }}>{pos.pair}</span>
                    <span className="text-foreground/60 text-[10px]">
                      {new Date(pos.open_date).toLocaleDateString()}
                    </span>
                    <span className="text-right tabular-nums text-foreground/70">
                      ${pos.stake_amount.toFixed(2)}
                    </span>
                    <span className="text-right tabular-nums">${pos.current_rate.toFixed(4)}</span>
                    <span
                      className="text-right tabular-nums font-semibold"
                      style={{ color: profitPos ? "#00ff88" : "#ff4444" }}
                    >
                      {profitPos ? "+" : ""}{pos.profit_pct.toFixed(2)}%
                    </span>
                    <span
                      className="text-right tabular-nums font-semibold"
                      style={{ color: profitPos ? "#00ff88" : "#ff4444" }}
                    >
                      {profitPos ? "+" : ""}${pos.profit_abs.toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Setup instructions when disabled */}
        {!status?.enabled && (
          <div className="rounded-xl border border-warn/30 bg-warn/5 p-4 space-y-2">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-warn">
              Crypto Module Disabled
            </p>
            <p className="font-mono text-[11px] text-muted-foreground">
              To enable crypto trading, set <code className="text-warn">CRYPTO_ENABLED=true</code> in your{" "}
              <code className="text-warn">.env</code> file and restart the engine.
            </p>
            <p className="font-mono text-[11px] text-muted-foreground">
              Install and start Freqtrade separately:{" "}
              <code className="text-foreground/70">bash scripts/setup_freqtrade.sh</code>
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
