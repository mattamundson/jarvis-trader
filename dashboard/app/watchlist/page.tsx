"use client";

import React, { useState, useCallback } from "react";
import useSWR from "swr";
import {
  Activity,
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
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type { WatchlistItem, MGCSignalResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { WatchlistScanWidget } from "@/components/WatchlistScanWidget";
import { SymbolPerformanceWidget } from "@/components/SymbolPerformanceWidget";
import { PerformanceTrendWidget } from "@/components/PerformanceTrendWidget";
import { VIXRegimeCard } from "@/components/VIXRegimeCard";
import { CurrentSignalWidget } from "@/components/CurrentSignalWidget";
import { MesContractSpecCard } from "@/components/MesContractSpecCard";

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
    status: "RESEARCH",
  },
  {
    symbol: "MES",
    description: "Micro E-mini S&P 500",
    exchange: "CME Globex",
    multiplier: 5,
    tick: 0.25,
    status: "DO NOT TRADE",
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
    strategy: "STC adaptive regime + ATR stops",
    wfe: "0.88 (EXCELLENT)",
    riskPerTrade: "0.25% of account",
    adaptiveRegime: "ON",
    clearedDate: "2026-03-29",
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

function formatPrice(price: number | null, symbol: string): string {
  if (price == null) return "\u2014";
  if (price >= 1000) {
    return price.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return price.toFixed(2);
}

function formatChangePct(pct: number | null): string {
  if (pct == null) return "\u2014";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

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

          {/* Paper Trading Config */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2">
              Paper Trading Configuration
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
      {/* Main content */}
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-8 space-y-6">

        {/* Current STC Signal Widget */}
        <CurrentSignalWidget symbol="MES" />

        {/* Watchlist Scan Widget */}
        <WatchlistScanWidget symbols="MES,MNQ,MCL,MGC" />

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
                                ? `$${formatPrice(row.last_price, row.symbol)}`
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
        <PerformanceTrendWidget />

        {/* VIX Regime Filter Card */}
        <VIXRegimeCard />

        {/* Symbol Performance Widget */}
        <SymbolPerformanceWidget />

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
