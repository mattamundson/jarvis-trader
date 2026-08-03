"use client";

import React, { useState, useCallback, useEffect } from "react";
import useSWR from "swr";
import {
  Activity,
  ArrowLeft,
  Plus,
  Trash2,
  RefreshCw,
  Play,
  TrendingUp,
  TrendingDown,
  Minus,
  Check,
  X,
  ChevronUp,
  ChevronDown,
  Info,
  Crosshair,
  Clock,
  AlertCircle,
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type { WatchlistItem, MGCSignalResponse } from "@/lib/api";
import {
  fetchHonestTrades,
  type HonestTradeSet,
  bySymbolStats,
  type SymbolStat as HonestSymbolStat,
  dedupCaveat,
} from "@/lib/honestTrades";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPrice, formatChangePct } from "@/lib/watchlistFormatters";
// WatchlistScanWidget and SymbolPerformanceWidget are inlined below with the
// double-json bug fixed (those components called fetchEngine().then(r=>r.json())
// but fetchEngine already returns parsed JSON, so r.json() threw TypeError and
// data stayed null → permanent skeleton).
import { PerformanceTrendWidget } from "@/components/PerformanceTrendWidget";
import { VIXRegimeCard } from "@/components/VIXRegimeCard";
import { CurrentSignalWidget } from "@/components/CurrentSignalWidget";
import { MesContractSpecCard } from "@/components/MesContractSpecCard";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

// ── Inline: WatchlistScanWidget ────────────────────────────────────────────
// Fixed: fetchEngine already returns parsed JSON; removed double .json() call
// that caused TypeError → data stayed null → permanent skeleton.

type TFResult = { alignment: string; stc_value: number; signal: string };
type SymbolResult = {
  symbol: string;
  recommendation: "BUY" | "SELL" | "WAIT";
  alignment: string;
  timeframes: Record<string, TFResult>;
  error?: string | null;
};
type ScanData = {
  symbols: SymbolResult[];
  market_bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  buy_count: number;
  sell_count: number;
  wait_count: number;
  scanned_at: string;
};

const REC_VARIANT_SCAN: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  BUY: "bull",
  SELL: "bear",
  WAIT: "neutral",
};
const BIAS_VARIANT_SCAN: Record<string, "bull" | "bear" | "neutral"> = {
  BULLISH: "bull",
  BEARISH: "bear",
  NEUTRAL: "neutral",
};

function WatchlistScanWidget({ symbols = "MES,MNQ,MCL,MGC" }: { symbols?: string }) {
  const [scanData, setScanData] = useState<ScanData | null>(null);
  const [scanWidgetLoading, setScanWidgetLoading] = useState(false);
  const [scanWidgetError, setScanWidgetError] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<string | null>(null);

  const runScan = useCallback(() => {
    setScanWidgetLoading(true);
    setScanWidgetError(null);
    fetchEngine<ScanData>(`/watchlist/scan?symbols=${encodeURIComponent(symbols)}`)
      .then((d) => {
        setScanData(d);
        setLastScan(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
      })
      .catch((err: unknown) => {
        setScanWidgetError(err instanceof Error ? err.message : "Scan unavailable");
      })
      .finally(() => setScanWidgetLoading(false));
  }, [symbols]);

  useEffect(() => {
    runScan();
    const id = setInterval(runScan, 300_000);
    return () => clearInterval(id);
  }, [runScan]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Watchlist Scan</CardTitle>
          <div className="flex items-center gap-2">
            {scanData && (
              <Badge variant={BIAS_VARIANT_SCAN[scanData.market_bias] ?? "neutral"}>
                {scanData.market_bias}
              </Badge>
            )}
            <button
              type="button"
              onClick={runScan}
              disabled={scanWidgetLoading}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Re-scan"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${scanWidgetLoading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastScan && (
          <p className="text-xs text-muted-foreground">Last scan: {lastScan}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {scanWidgetLoading && !scanData ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-12 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : scanWidgetError && !scanData ? (
          <div className="px-4 pb-4 flex items-center gap-2 text-xs text-muted-foreground">
            <AlertCircle className="h-4 w-4 text-bear/70 shrink-0" />
            Scan unavailable — engine may not support this endpoint
          </div>
        ) : !scanData ? (
          <div className="px-4 pb-4 text-xs text-muted-foreground">No scan data yet.</div>
        ) : (
          <>
            <div className="divide-y divide-border">
              {scanData.symbols.map((s) => (
                <div key={s.symbol} className="px-4 py-2.5 flex items-center justify-between">
                  <div>
                    <span className="text-sm font-mono font-semibold">{s.symbol}</span>
                    {s.error ? (
                      <p className="text-xs text-muted-foreground">{s.error}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground">{s.alignment}</p>
                    )}
                  </div>
                  <Badge variant={REC_VARIANT_SCAN[s.recommendation] ?? "neutral"}>
                    {s.recommendation}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="px-4 py-2 border-t border-border bg-muted/30 flex gap-3 text-xs text-muted-foreground">
              <span className="text-bull">{scanData.buy_count} BUY</span>
              <span className="text-bear">{scanData.sell_count} SELL</span>
              <span>{scanData.wait_count} WAIT</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Inline: SymbolPerformanceWidget ────────────────────────────────────────
// Migrated from /analytics/trades/by-symbol (over-counted re-logged winners)
// to bySymbolStats(honestSet.trades) — deduped at read time via master-api.
// Best/Worst per-trade fields are not in the honest record; those columns are
// omitted rather than fabricated.

function spPnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}
function spFormatPnl(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}
function spWinRateClass(rate: number): string {
  // rate is 0..1 from honestTrades
  if (rate >= 0.55) return "text-bull";
  if (rate < 0.45) return "text-bear";
  return "text-muted-foreground";
}

function SymbolPerformanceWidget() {
  const [spHonest, setSpHonest] = useState<HonestTradeSet | null>(null);
  const [spLoading, setSpLoading] = useState(false);
  const [spError, setSpError] = useState<string | null>(null);
  const [spLastUpdated, setSpLastUpdated] = useState<string | null>(null);

  const fetchSpData = useCallback(() => {
    setSpLoading(true);
    setSpError(null);
    fetchHonestTrades()
      .then((set) => {
        setSpHonest(set);
        setSpLastUpdated(
          new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        );
      })
      .catch((err: unknown) => {
        setSpError(err instanceof Error ? err.message : "Unavailable");
      })
      .finally(() => setSpLoading(false));
  }, []);

  useEffect(() => {
    fetchSpData();
    const id = setInterval(fetchSpData, 300_000);
    return () => clearInterval(id);
  }, [fetchSpData]);

  const symbolRows: HonestSymbolStat[] = spHonest ? bySymbolStats(spHonest.trades) : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Symbol Performance</CardTitle>
          <div className="flex items-center gap-2">
            {spHonest && (
              <span className="text-xs text-muted-foreground">
                {symbolRows.length} symbol{symbolRows.length !== 1 ? "s" : ""}
              </span>
            )}
            <button
              type="button"
              onClick={fetchSpData}
              disabled={spLoading}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${spLoading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {spLastUpdated && (
          <p className="text-xs text-muted-foreground">Updated: {spLastUpdated}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {spLoading && !spHonest ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : spError && !spHonest ? (
          <div className="px-4 pb-4 flex items-center gap-2 text-xs text-muted-foreground">
            <AlertCircle className="h-4 w-4 text-bear/70 shrink-0" />
            Symbol performance unavailable
          </div>
        ) : !spHonest || symbolRows.length === 0 ? (
          <div className="px-4 pb-4 text-sm text-muted-foreground">
            No symbol data yet.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="px-4 py-2 text-left font-medium text-muted-foreground">Symbol</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Trades</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">W/L</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Win Rate</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Total P&amp;L</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Avg P&amp;L</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Profit Factor</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {symbolRows.map((s) => {
                    const avgPnl = s.trades > 0 ? s.net / s.trades : 0;
                    return (
                      <tr key={s.symbol} className="hover:bg-muted/20 transition-colors">
                        <td className="px-4 py-2.5 font-mono font-semibold">{s.symbol}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{s.trades}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">
                          <span className="text-bull">{s.wins}</span>
                          <span className="text-muted-foreground mx-0.5">/</span>
                          <span className="text-bear">{s.losses}</span>
                        </td>
                        <td className={`px-4 py-2.5 text-right tabular-nums ${spWinRateClass(s.winRate)}`}>
                          {(s.winRate * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <Badge variant={spPnlVariant(s.net)}>{spFormatPnl(s.net)}</Badge>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <Badge variant={spPnlVariant(avgPnl)}>{spFormatPnl(avgPnl)}</Badge>
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                          {s.profitFactor != null ? s.profitFactor.toFixed(2) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-4 py-2 border-t border-border text-[10px] text-muted-foreground">
              {dedupCaveat(spHonest)} · sourced from deduped record
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Types ──────────────────────────────────────────────────────────────────

interface DecisionRecord {
  id: number;
  symbol: string;
  action: string;
  confidence: number;
  timestamp: string;
  source: string;
  summary?: string;
}

interface DecisionHistoryResponse {
  decisions: DecisionRecord[];
  count: number;
}

interface WatchlistRow extends WatchlistItem {
  lastSignal?: string;
  lastSignalTime?: string;
  lastSignalConfidence?: number;
}

// ── Static Instrument Specs ──────────────────────────────────────────────

type InstrumentStatus = "ACTIVE" | "RESEARCH" | "DO NOT TRADE";

interface InstrumentSpec {
  symbol: string;
  description: string;
  exchange: string;
  multiplier: number;
  tick: number;
  status: InstrumentStatus;
}

const INSTRUMENT_SPECS: InstrumentSpec[] = [
  {
    symbol: "MGC",
    description: "Micro Gold Futures",
    exchange: "CME Globex",
    multiplier: 10,
    tick: 0.10,
    status: "ACTIVE",
  },
  {
    symbol: "MNQ",
    description: "Micro Nasdaq-100 Futures",
    exchange: "CME Globex",
    multiplier: 2,
    tick: 0.25,
    status: "DO NOT TRADE",
  },
  {
    symbol: "MES",
    description: "Micro E-mini S&P 500",
    exchange: "CME Globex",
    multiplier: 5,
    tick: 0.25,
    status: "ACTIVE",
  },
  {
    symbol: "MCL",
    description: "Micro WTI Crude Oil",
    exchange: "CME Globex",
    multiplier: 100,
    tick: 0.01,
    status: "DO NOT TRADE",
  },
  {
    symbol: "SPY",
    description: "SPDR S&P 500 ETF",
    exchange: "NYSE Arca",
    multiplier: 100,
    tick: 0.01,
    status: "DO NOT TRADE",
  },
];

// ── MGC Contract Details (static) ────────────────────────────────────────

const MGC_DETAILS = {
  fullName: "Micro Gold Futures (MGC)",
  exchange: "CME Globex",
  contractSize: "10 troy ounces",
  tickSize: "$0.10 per ounce = $1.00 per tick",
  pointValue: "$10 per point (1 point = $10)",
  tradingHours: "Sun-Fri 6:00 PM - 5:00 PM ET (23h session)",
  settlementType: "Physical delivery (cash-settled for micros)",
  marginInitial: "~$1,050 (subject to change)",
  marginMaintenance: "~$950 (subject to change)",
  monthlyExpiry: "Feb, Apr, Jun, Aug, Oct, Dec (even months)",
  paperConfig: {
    strategy: "gate-v2 trend rank4",
    wfe: "1.0 (PASS via alt)",
    riskPerTrade: "0.25% of account",
    adaptiveRegime: "ON",
    clearedDate: "2026-05-31",
    contracts: "1 MGC per signal",
  },
};

// ── Constants ──────────────────────────────────────────────────────────────

const PRICE_REFRESH_MS = 15_000;
const SIGNAL_REFRESH_MS = 60_000;

// ── Fetcher ────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Formatters ─────────────────────────────────────────────────────────────
// formatPrice / formatChangePct now live in lib/watchlistFormatters.ts
// (GT-18 fix + unit tests -- see tests/watchlistFormatters.node.test.ts).

function formatTimestamp(ts: string | undefined): string {
  if (!ts) return "\u2014";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function changeColorClass(pct: number | null): string {
  if (pct == null || Math.abs(pct) < 0.00005) return "text-muted-foreground";
  return pct > 0 ? "text-bull" : "text-bear";
}

// ── Signal badge ───────────────────────────────────────────────────────────

function SignalBadge({ signal }: { signal: string | undefined }) {
  if (!signal) return <span className="text-muted-foreground font-mono text-xs">\u2014</span>;

  const upper = signal.toUpperCase();

  if (upper === "BUY" || upper === "LONG") {
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-xs font-bold bg-bull/15 text-bull border border-bull/30">
        <TrendingUp className="h-3 w-3" />
        {upper}
      </span>
    );
  }
  if (upper === "SELL" || upper === "SHORT") {
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-xs font-bold bg-bear/15 text-bear border border-bear/30">
        <TrendingDown className="h-3 w-3" />
        {upper}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-xs font-semibold bg-muted text-muted-foreground border border-border">
      <Minus className="h-3 w-3" />
      HOLD
    </span>
  );
}

// ── Checkbox ───────────────────────────────────────────────────────────────

function RowCheckbox({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={`h-4 w-4 rounded border flex items-center justify-center transition-colors ${
        checked
          ? "bg-accent border-accent text-accent-foreground"
          : "border-border bg-background hover:border-accent/60"
      }`}
      aria-checked={checked}
      role="checkbox"
    >
      {checked && <Check className="h-2.5 w-2.5" />}
    </button>
  );
}

// ── Status helpers ─────────────────────────────────────────────────────────

function instrumentStatusBadge(status: InstrumentStatus) {
  if (status === "ACTIVE") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-bull/30 bg-bull/10 px-2.5 py-0.5 text-[10px] font-bold text-bull tracking-wider">
        ACTIVE (paper)
      </span>
    );
  }
  if (status === "RESEARCH") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-warn/30 bg-warn/10 px-2.5 py-0.5 text-[10px] font-bold text-warn tracking-wider">
        RESEARCH
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-bear/30 bg-bear/10 px-2.5 py-0.5 text-[10px] font-bold text-bear tracking-wider">
      DO NOT TRADE
    </span>
  );
}

// ── Instrument Specs Table ─────────────────────────────────────────────────

function InstrumentSpecsTable({ mgcSignal }: { mgcSignal: MGCSignalResponse | null }) {
  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/20">
            <Crosshair className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Instrument Universe
            </p>
            <p className="text-[10px] text-muted-foreground">
              Tracked futures and ETFs with contract specifications
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Symbol
                </th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Description
                </th>
                <th className="px-4 py-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Exchange
                </th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Multiplier
                </th>
                <th className="px-4 py-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Tick
                </th>
                <th className="px-4 py-3 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-center font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                  Last Signal
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {INSTRUMENT_SPECS.map((inst) => {
                const isMGC = inst.symbol === "MGC";
                const signal = isMGC ? mgcSignal?.direction : undefined;
                return (
                  <tr
                    key={inst.symbol}
                    className={`transition-colors ${isMGC ? "bg-accent/5 hover:bg-accent/10" : "hover:bg-muted/20"}`}
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono font-bold text-foreground text-sm">
                        {inst.symbol}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {inst.description}
                    </td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-[11px]">
                      {inst.exchange}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-foreground">
                      {inst.multiplier}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-foreground">
                      {inst.tick.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {instrumentStatusBadge(inst.status)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {isMGC && signal ? (
                        <SignalBadge signal={signal} />
                      ) : (
                        <span className="text-muted-foreground font-mono text-xs">{"\u2014"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── MGC Details Card ───────────────────────────────────────────────────────

function MGCDetailsCard({ mgcSignal }: { mgcSignal: MGCSignalResponse | null }) {
  return (
    <Card className="border-bull/20">
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-bull/20">
            <Info className="h-4 w-4 text-bull" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-bull">
              MGC — Active Instrument Details
            </p>
            <p className="text-[10px] text-muted-foreground">
              Contract specifications and paper trading configuration
            </p>
          </div>
          <Badge variant="bull" className="ml-auto text-[10px]">
            PAPER ACTIVE
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Contract Specs */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2">
              Contract Specifications
            </p>
            <div className="space-y-1.5">
              {[
                ["Full Name", MGC_DETAILS.fullName],
                ["Exchange", MGC_DETAILS.exchange],
                ["Contract Size", MGC_DETAILS.contractSize],
                ["Tick Size", MGC_DETAILS.tickSize],
                ["Point Value", MGC_DETAILS.pointValue],
                ["Settlement", MGC_DETAILS.settlementType],
                ["Expiry Months", MGC_DETAILS.monthlyExpiry],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-baseline gap-4">
                  <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
                  <span className="text-[11px] font-mono text-foreground text-right">{value}</span>
                </div>
              ))}
            </div>

            <div className="mt-3 pt-2 border-t border-border space-y-1.5">
              {[
                ["Initial Margin", MGC_DETAILS.marginInitial],
                ["Maintenance Margin", MGC_DETAILS.marginMaintenance],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-baseline gap-4">
                  <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
                  <span className="text-[11px] font-mono text-warn text-right">{value}</span>
                </div>
              ))}
            </div>

            <div className="mt-3 pt-2 border-t border-border">
              <div className="flex justify-between items-baseline gap-4">
                <span className="text-[11px] text-muted-foreground shrink-0">Trading Hours</span>
                <span className="text-[11px] font-mono text-foreground text-right flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {MGC_DETAILS.tradingHours}
                </span>
              </div>
            </div>
          </div>

          {/* Paper Trading Config — STATIC reference snapshot, not live engine state */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2 flex items-center gap-1.5">
              Paper Trading Configuration
              <span className="rounded border border-muted-foreground/30 bg-muted/20 px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-widest text-muted-foreground/70">
                Static reference
              </span>
            </p>
            <div className="space-y-1.5">
              {[
                ["Strategy", MGC_DETAILS.paperConfig.strategy],
                ["WFE Score", MGC_DETAILS.paperConfig.wfe],
                ["Risk Per Trade", MGC_DETAILS.paperConfig.riskPerTrade],
                ["Adaptive Regime", MGC_DETAILS.paperConfig.adaptiveRegime],
                ["Cleared Date", MGC_DETAILS.paperConfig.clearedDate],
                ["Position Size", MGC_DETAILS.paperConfig.contracts],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-baseline gap-4">
                  <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
                  <span className={`text-[11px] font-mono text-right ${
                    label === "WFE Score" ? "text-bull" :
                    label === "Adaptive Regime" ? "text-accent" :
                    "text-foreground"
                  }`}>{value}</span>
                </div>
              ))}
            </div>

            {/* Live signal from /paper/mgc-signal */}
            {mgcSignal && (
              <div className="mt-3 pt-2 border-t border-border">
                <p className="text-[10px] font-bold text-accent uppercase tracking-widest mb-2">
                  Latest Signal (polled every 60s)
                </p>
                <div className="space-y-1.5">
                  <div className="flex justify-between items-baseline gap-4">
                    <span className="text-[11px] text-muted-foreground">Direction</span>
                    <span className={`text-[11px] font-mono font-bold ${
                      mgcSignal.direction === "LONG" ? "text-bull" :
                      mgcSignal.direction === "SHORT" ? "text-bear" :
                      "text-muted-foreground"
                    }`}>
                      {mgcSignal.direction ?? "\u2014"}
                    </span>
                  </div>
                  {mgcSignal.entry_price != null && (
                    <div className="flex justify-between items-baseline gap-4">
                      <span className="text-[11px] text-muted-foreground">Entry</span>
                      <span className="text-[11px] font-mono tabular-nums text-foreground">
                        ${mgcSignal.entry_price.toFixed(2)}
                      </span>
                    </div>
                  )}
                  {mgcSignal.stop_level != null && (
                    <div className="flex justify-between items-baseline gap-4">
                      <span className="text-[11px] text-muted-foreground">Stop</span>
                      <span className="text-[11px] font-mono tabular-nums text-bear">
                        ${mgcSignal.stop_level.toFixed(2)}
                      </span>
                    </div>
                  )}
                  {mgcSignal.target_1 != null && (
                    <div className="flex justify-between items-baseline gap-4">
                      <span className="text-[11px] text-muted-foreground">Target 1</span>
                      <span className="text-[11px] font-mono tabular-nums text-bull">
                        ${mgcSignal.target_1.toFixed(2)}
                      </span>
                    </div>
                  )}
                  {mgcSignal.regime && (
                    <div className="flex justify-between items-baseline gap-4">
                      <span className="text-[11px] text-muted-foreground">Regime</span>
                      <span className="text-[11px] font-mono text-info">
                        {mgcSignal.regime}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function WatchlistPage() {
  // ── State ────────────────────────────────────────────────────────────────
  const [addSymbol, setAddSymbol] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [addLoading, setAddLoading] = useState(false);
  const [removeLoading, setRemoveLoading] = useState<string | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanResult, setScanResult] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sortAsc, setSortAsc] = useState(true);

  // ── Data fetching ─────────────────────────────────────────────────────────
  const {
    data: watchlistRaw,
    mutate: mutateWatchlist,
    isLoading: wlLoading,
  } = useSWR<WatchlistItem[]>("/watchlist", fetcher, {
    refreshInterval: PRICE_REFRESH_MS,
  });

  // Fetch last signal per symbol from decision history
  const {
    data: decisionsData,
    mutate: mutateDecisions,
  } = useSWR<DecisionHistoryResponse>(
    "/portfolio/history/decisions?limit=200",
    fetcher,
    { refreshInterval: PRICE_REFRESH_MS }
  );

  // Fetch MGC signal every 60s
  const { data: mgcSignal } = useSWR<MGCSignalResponse>(
    "/paper/mgc-signal",
    fetcher,
    { refreshInterval: SIGNAL_REFRESH_MS, shouldRetryOnError: false }
  );

  // ── Merge watchlist + decisions ──────────────────────────────────────────
  const watchlist: WatchlistRow[] = React.useMemo(() => {
    const items = watchlistRaw ?? [];
    const decisions = decisionsData?.decisions ?? [];

    // Build map of symbol -> last decision
    const lastBySymbol = new Map<string, DecisionRecord>();
    for (const d of decisions) {
      const sym = d.symbol?.toUpperCase();
      if (!sym) continue;
      if (!lastBySymbol.has(sym) || new Date(d.timestamp) > new Date(lastBySymbol.get(sym)!.timestamp)) {
        lastBySymbol.set(sym, d);
      }
    }

    const rows: WatchlistRow[] = items.map((item) => {
      const last = lastBySymbol.get(item.symbol.toUpperCase());
      return {
        ...item,
        lastSignal: last?.action,
        lastSignalTime: last?.timestamp,
        lastSignalConfidence: last?.confidence,
      };
    });

    // Sort alphabetically
    return rows.sort((a, b) =>
      sortAsc
        ? a.symbol.localeCompare(b.symbol)
        : b.symbol.localeCompare(a.symbol)
    );
  }, [watchlistRaw, decisionsData, sortAsc]);

  // ── Selection helpers ────────────────────────────────────────────────────
  const allSelected =
    watchlist.length > 0 && watchlist.every((r) => selected.has(r.symbol));
  const someSelected = watchlist.some((r) => selected.has(r.symbol));

  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(watchlist.map((r) => r.symbol)));
    }
  }, [allSelected, watchlist]);

  const toggleSelect = useCallback((sym: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  }, []);

  // ── Add symbol ───────────────────────────────────────────────────────────
  const handleAdd = useCallback(async () => {
    const sym = addSymbol.trim().toUpperCase();
    if (!sym) {
      setAddError("Symbol must not be empty.");
      return;
    }
    setAddLoading(true);
    setAddError(null);
    try {
      await fetchEngine("/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym }),
      });
      setAddSymbol("");
      setShowAddForm(false);
      mutateWatchlist();
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : "Failed to add symbol.");
    } finally {
      setAddLoading(false);
    }
  }, [addSymbol, mutateWatchlist]);

  const handleAddKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleAdd();
      if (e.key === "Escape") {
        setShowAddForm(false);
        setAddSymbol("");
        setAddError(null);
      }
    },
    [handleAdd]
  );

  // ── Remove symbol ────────────────────────────────────────────────────────
  const handleRemove = useCallback(
    async (symbol: string) => {
      setRemoveLoading(symbol);
      try {
        await fetchEngine(`/watchlist/${encodeURIComponent(symbol)}`, {
          method: "DELETE",
        });
        setSelected((prev) => {
          const next = new Set(prev);
          next.delete(symbol);
          return next;
        });
        mutateWatchlist();
      } catch (e) {
        console.error("Remove failed:", e);
      } finally {
        setRemoveLoading(null);
      }
    },
    [mutateWatchlist]
  );

  // ── Run scan ─────────────────────────────────────────────────────────────
  const handleScan = useCallback(async () => {
    const symbols =
      selected.size > 0
        ? [...selected]
        : watchlist.map((r) => r.symbol);

    if (symbols.length === 0) return;
    setScanLoading(true);
    setScanResult(null);

    try {
      const futures_symbols = new Set(["MES", "MNQ", "MCL", "MGC", "MHG", "MYM", "M2K"]);
      const results: string[] = [];
      for (const sym of symbols) {
        try {
          const res = await fetchEngine<{ final_action?: string; summary?: string }>("/pipeline/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              symbol: sym,
              is_futures: futures_symbols.has(sym),
            }),
          });
          results.push(`${sym}: ${(res.final_action ?? "hold").toUpperCase()}`);
        } catch {
          results.push(`${sym}: ERROR`);
        }
      }
      setScanResult(results.join(" | "));
      mutateDecisions();
      mutateWatchlist();
    } finally {
      setScanLoading(false);
    }
  }, [selected, watchlist, mutateDecisions, mutateWatchlist]);

  // ── Render ────────────────────────────────────────────────────────────────
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
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a
                href="/"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Dashboard
              </a>
              <a
                href="/analysis"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Analysis
              </a>
              <a
                href="/backtest"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Backtest
              </a>
              <a
                href="/performance"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Performance
              </a>
              <a
                href="/validation"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Validation
              </a>
              <a
                href="/paper"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Paper Trading
              </a>
              <a
                href="/journal"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Journal
              </a>
              <a
                href="/watchlist"
                className="text-xs font-semibold text-foreground border-b border-accent pb-0.5 transition-colors"
              >
                Watchlist
              </a>
              <a
                href="/scorecard"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Scorecard
              </a>
              <a
                href="/settings"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Settings
              </a>
              <a
                href="/health"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Health
              </a>
            </nav>
          </div>

          <a
            href="/"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Dashboard
          </a>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-8 space-y-6">

        {/* Current STC Signal Widget */}
        <WidgetErrorBoundary name="Current Signal">
          <CurrentSignalWidget symbol="MES" />
        </WidgetErrorBoundary>

        {/* Watchlist Scan Widget */}
        <WidgetErrorBoundary name="Watchlist Scan">
          <WatchlistScanWidget symbols="MES,MNQ,MCL,MGC" />
        </WidgetErrorBoundary>

        {/* Page title + controls */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-foreground tracking-tight flex items-center gap-2">
              <Crosshair className="h-6 w-6 text-accent" />
              Watchlist
              {watchlist.length > 0 && (
                <span className="ml-2 text-base font-normal text-muted-foreground">
                  ({watchlist.length} instrument{watchlist.length !== 1 ? "s" : ""})
                </span>
              )}
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Instrument universe, contract specs, and live signal status
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={handleScan}
              disabled={scanLoading || watchlist.length === 0}
              className="flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {scanLoading ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {scanLoading
                ? "Scanning..."
                : selected.size > 0
                ? `Scan ${selected.size} selected`
                : "Run Scan Now"}
            </button>

            <button
              type="button"
              onClick={() => {
                setShowAddForm((v) => !v);
                setAddError(null);
              }}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted transition-colors"
            >
              {showAddForm ? (
                <X className="h-3.5 w-3.5" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              {showAddForm ? "Cancel" : "Add Symbol"}
            </button>
          </div>
        </div>

        {/* Scan result toast */}
        {scanResult && (
          <div className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-2.5 text-xs font-mono text-accent">
            Scan complete: {scanResult}
          </div>
        )}

        {/* Inline Add Symbol form */}
        {showAddForm && (
          <Card className="border-accent/30">
            <CardContent className="pt-4 pb-4">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Add Symbol
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={addSymbol}
                  onChange={(e) => {
                    setAddSymbol(e.target.value.toUpperCase());
                    setAddError(null);
                  }}
                  onKeyDown={handleAddKeyDown}
                  placeholder="e.g. MES, MNQ, SPY"
                  autoFocus
                  className="h-8 rounded-md border border-border bg-background px-3 py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent/60 w-48"
                />
                <button
                  type="button"
                  onClick={handleAdd}
                  disabled={addLoading || !addSymbol.trim()}
                  className="flex items-center gap-1.5 h-8 rounded-md border border-accent/50 bg-accent/10 px-3 text-xs font-semibold text-accent hover:bg-accent/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {addLoading ? (
                    <RefreshCw className="h-3 w-3 animate-spin" />
                  ) : (
                    <Plus className="h-3 w-3" />
                  )}
                  Add
                </button>
              </div>
              {addError && (
                <p className="mt-2 text-xs text-bear">{addError}</p>
              )}
              <p className="mt-2 text-[11px] text-muted-foreground">
                Futures (MES, MNQ, MCL, MGC, MHG, MYM, M2K) are added to the
                futures watchlist. All other symbols go to the equities watchlist.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Instrument Specs Table (Static) */}
        <InstrumentSpecsTable mgcSignal={mgcSignal ?? null} />

        {/* MGC Active Instrument Details */}
        <MGCDetailsCard mgcSignal={mgcSignal ?? null} />

        {/* Dynamic Watchlist Table (from engine) */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
            Live Price Feed
          </p>
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="w-10 px-4 py-3">
                        <RowCheckbox
                          checked={allSelected}
                          onChange={toggleSelectAll}
                        />
                      </th>

                      <th className="px-4 py-3 text-left">
                        <button
                          type="button"
                          onClick={() => setSortAsc((v) => !v)}
                          className="flex items-center gap-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors"
                        >
                          Symbol
                          {sortAsc ? (
                            <ChevronUp className="h-3 w-3" />
                          ) : (
                            <ChevronDown className="h-3 w-3" />
                          )}
                        </button>
                      </th>

                      <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Type
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Last Price
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        24h Change
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Last Signal
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Confidence
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Last Scan
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>

                  <tbody className="divide-y divide-border">
                    {wlLoading && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-xs text-muted-foreground">
                          <RefreshCw className="h-4 w-4 animate-spin inline mr-2" />
                          Loading watchlist...
                        </td>
                      </tr>
                    )}

                    {!wlLoading && watchlist.length === 0 && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-xs text-muted-foreground">
                          No instruments in watchlist.{" "}
                          <button
                            type="button"
                            onClick={() => setShowAddForm(true)}
                            className="text-accent underline hover:no-underline"
                          >
                            Add a symbol
                          </button>{" "}
                          to get started.
                        </td>
                      </tr>
                    )}

                    {watchlist.map((row) => {
                      const isSelected = selected.has(row.symbol);
                      const pctColor = changeColorClass(row.change_pct);
                      const isRemoving = removeLoading === row.symbol;

                      return (
                        <tr
                          key={row.symbol}
                          className={`transition-colors ${
                            isSelected
                              ? "bg-accent/5 hover:bg-accent/10"
                              : "hover:bg-muted/40"
                          }`}
                        >
                          <td className="w-10 px-4 py-3">
                            <RowCheckbox
                              checked={isSelected}
                              onChange={() => toggleSelect(row.symbol)}
                            />
                          </td>

                          <td className="px-4 py-3">
                            <span className="font-mono font-bold text-foreground text-sm">
                              {row.symbol}
                            </span>
                            {row.name && row.name !== row.symbol && (
                              <p className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                {row.name}
                              </p>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            <Badge
                              variant={row.type === "futures" ? "neutral" : "info"}
                              className="text-[10px]"
                            >
                              {row.type}
                            </Badge>
                          </td>

                          <td className="px-4 py-3 text-right">
                            <span className="font-mono tabular-nums text-sm text-foreground">
                              {row.last_price != null
                                ? `$${formatPrice(row.last_price)}`
                                : "\u2014"}
                            </span>
                          </td>

                          <td className="px-4 py-3 text-right">
                            <span className={`font-mono tabular-nums text-sm font-semibold ${pctColor}`}>
                              {formatChangePct(row.change_pct)}
                            </span>
                          </td>

                          <td className="px-4 py-3 text-center">
                            <SignalBadge signal={row.lastSignal} />
                          </td>

                          <td className="px-4 py-3 text-center">
                            {row.lastSignalConfidence != null ? (
                              <span className="font-mono tabular-nums text-xs text-muted-foreground">
                                {(row.lastSignalConfidence * 100).toFixed(0)}%
                              </span>
                            ) : (
                              <span className="text-muted-foreground font-mono text-xs">{"\u2014"}</span>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            <span className="font-mono text-xs text-muted-foreground tabular-nums">
                              {formatTimestamp(row.lastSignalTime)}
                            </span>
                          </td>

                          <td className="px-4 py-3 text-center">
                            <button
                              type="button"
                              onClick={() => handleRemove(row.symbol)}
                              disabled={isRemoving}
                              title={`Remove ${row.symbol}`}
                              className="inline-flex items-center justify-center h-7 w-7 rounded-md border border-border text-muted-foreground hover:border-bear/50 hover:text-bear hover:bg-bear/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                            >
                              {isRemoving ? (
                                <RefreshCw className="h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {someSelected && (
                <div className="border-t border-border px-4 py-2.5 flex items-center gap-3 bg-muted/30">
                  <span className="text-xs text-muted-foreground">
                    {selected.size} selected
                  </span>
                  <button
                    type="button"
                    onClick={handleScan}
                    disabled={scanLoading}
                    className="flex items-center gap-1 text-xs text-accent hover:text-accent/80 font-semibold transition-colors"
                  >
                    <Play className="h-3 w-3" />
                    Scan selected
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelected(new Set())}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Clear selection
                  </button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Performance Trend Widget */}
        <WidgetErrorBoundary name="Performance Trend">
          <PerformanceTrendWidget />
        </WidgetErrorBoundary>

        {/* VIX Regime Filter Card */}
        <VIXRegimeCard />

        {/* Symbol Performance Widget */}
        <WidgetErrorBoundary name="Symbol Performance">
          <SymbolPerformanceWidget />
        </WidgetErrorBoundary>

        {/* MES Contract Spec Card */}
        <MesContractSpecCard />

        {/* Info footer */}
        <p className="text-[11px] text-muted-foreground text-center pb-4">
          Prices sourced from Yahoo Finance via the JARVIS engine. Watchlist changes
          are held in memory and reset when the engine restarts. MGC signal polled every 60s from /paper/mgc-signal.
        </p>
      </main>
    </div>
  );
}
