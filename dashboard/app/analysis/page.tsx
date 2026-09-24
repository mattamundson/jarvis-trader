"use client";

import dynamic from "next/dynamic";
import React, { useState } from "react";
import Link from "next/link";
import { Activity, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import {
  analyzeJarvisSymbol,
  JARVIS_QUICK_ANALYSIS_PERIODS,
  normalizeJarvisSymbolInput,
  postEngine,
  type JarvisQuickAnalysisPeriod,
  type JarvisQuickAnalysisResponse,
} from "@/lib/api";
import { MarketContextStrip } from "@/components/charts/MarketContextStrip";
import { AuctionBiasCard } from "@/components/AuctionBiasCard";
import { SymbolTimeframeSelector } from "@/components/command-center/charts/SymbolTimeframeSelector";
import type { ChartSymbol, ChartTimeframe } from "@/hooks/useChartData";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

// Heavy 3D chart (three.js + @react-three/fiber) — only rendered on the non-default
// "terrain3d" tab, so load it on demand to keep three.js out of the initial /analysis bundle.
const PriceTerrain3D = dynamic(
  () => import("@/components/charts/PriceTerrain3D").then((m) => ({ default: m.PriceTerrain3D })),
  { ssr: false, loading: () => <div className="h-[400px] animate-pulse rounded bg-card" /> }
);

// lightweight-charts backed panel — keep it out of the initial /analysis bundle the
// same way PriceTerrain3D is deferred; the "jarvis" tab still shows a loading skeleton
// until the chunk arrives, but the JS itself only loads once the tab actually mounts.
const PriceChartPanel = dynamic(
  () => import("@/components/charts/PriceChartPanel").then((m) => ({ default: m.PriceChartPanel })),
  { ssr: false, loading: () => <div className="h-[460px] animate-pulse rounded-xl border border-border bg-card" /> }
);

type ChartView = "jarvis" | "terrain3d";

interface PipelineResult {
  symbol: string;
  is_futures: boolean;
  final_action: string;
  confidence: number;
  bull_score: number;
  bear_score: number;
  summary?: string;
  technical?: Record<string, unknown>;
  news?: Record<string, unknown>;
  social?: Record<string, unknown>;
  fundamental?: Record<string, unknown>;
  debate?: Record<string, unknown>;
  trader?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  fund_manager?: Record<string, unknown>;
  error?: string;
}

export default function AnalysisPage() {
  const [symbol, setSymbol] = useState("SPY");
  const [isFutures, setIsFutures] = useState(false);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [quickPeriod, setQuickPeriod] = useState<JarvisQuickAnalysisPeriod>("5d");
  const [quickLoading, setQuickLoading] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);
  const [quickResult, setQuickResult] = useState<JarvisQuickAnalysisResponse | null>(null);
  const [chartSymbol, setChartSymbol] = useState<ChartSymbol>("MES");
  const [chartTimeframe, setChartTimeframe] = useState<ChartTimeframe>("1h");
  const [chartView, setChartView] = useState<ChartView>("jarvis");

  const normalizedSymbol = normalizeJarvisSymbolInput(symbol);

  const runAnalysis = async () => {
    if (!normalizedSymbol || pipelineLoading) return;
    setPipelineLoading(true);
    setPipelineError(null);
    setPipelineResult(null);
    try {
      const data = await postEngine<PipelineResult>("/pipeline/run", {
        symbol: normalizedSymbol,
        is_futures: isFutures,
      });
      setPipelineResult(data);
      // Auto-expand top sections
      setExpanded({ technical: true, debate: true, trader: true });
    } catch (e) {
      setPipelineError(e instanceof Error ? e.message : "Pipeline failed");
    } finally {
      setPipelineLoading(false);
    }
  };

  const runQuickAnalysis = async () => {
    if (!normalizedSymbol || quickLoading) return;
    setQuickLoading(true);
    setQuickError(null);
    setQuickResult(null);
    try {
      const data = await analyzeJarvisSymbol({
        symbol: normalizedSymbol,
        period: quickPeriod,
      });
      setQuickResult(data);
    } catch (e) {
      setQuickError(e instanceof Error ? e.message : "Quick analysis failed");
    } finally {
      setQuickLoading(false);
    }
  };

  const toggle = (key: string) => setExpanded(p => ({ ...p, [key]: !p[key] }));

  const actionColor = (action: string) => {
    if (action === "buy") return "text-green-400";
    if (action === "sell") return "text-red-400";
    return "text-yellow-400";
  };

  const scoreBar = (score: number, color: string) => (
    <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
      <div
        className={`h-full rounded-full ${color}`}
        style={{ width: `${Math.min(100, score * 100)}%` }}
      />
    </div>
  );

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-5xl flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Activity className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER — Analysis</h1>
            <p className="text-xs text-muted-foreground">5-stage AI pipeline</p>
          </div>
          <span className="text-xs text-muted-foreground ml-auto">
            <Link href="/" className="hover:text-foreground transition-colors">← Dashboard</Link>
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-6 space-y-6">
        <ExploratoryBanner what="The analysis pipeline shows AI-generated market reads" />
        {/* Market view — JARVIS real-time candles (our bars) or 3D terrain.
            Futures are charted from our own data; TradingView's delayed CME embed
            is intentionally NOT offered here (see the Market Context strip below
            for where TradingView's hosted data is appropriate). */}
        <div className="space-y-3">
          <div className="flex items-center gap-1.5">
            {(
              [
                ["jarvis", "JARVIS Chart"],
                ["terrain3d", "3D Terrain"],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => setChartView(mode)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors ${
                  chartView === mode
                    ? "bg-accent/20 text-accent"
                    : "bg-background border border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {chartView === "jarvis" && (
            <PriceChartPanel
              symbol={chartSymbol}
              timeframe={chartTimeframe}
              onSymbolChange={setChartSymbol}
              onTimeframeChange={setChartTimeframe}
            />
          )}

          {chartView === "terrain3d" && (
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <SymbolTimeframeSelector
                symbol={chartSymbol}
                timeframe={chartTimeframe}
                onSymbol={setChartSymbol}
                onTimeframe={setChartTimeframe}
              />
              <div className="p-3">
                <PriceTerrain3D symbol={chartSymbol} />
              </div>
            </div>
          )}
        </div>

        {/* TradingView "where it makes sense": macro/market context (equities,
            indices, macro, crypto) where TV's hosted data is real-time enough. */}
        <MarketContextStrip />

        {/* Advisory ES/MES overnight-bias read (Saty + TPO + Corey synthesis).
            Fixed to MES — the only symbol GET /auction/bias/{symbol} serves in v1. */}
        <AuctionBiasCard symbol="MES" />

        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
            Quick Gemini Snapshot
          </p>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Lookback</label>
              <select
                className="rounded-lg border border-border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
                value={quickPeriod}
                onChange={(e) => setQuickPeriod(e.target.value as JarvisQuickAnalysisPeriod)}
              >
                {JARVIS_QUICK_ANALYSIS_PERIODS.map((period) => (
                  <option key={period} value={period}>
                    {period}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={runQuickAnalysis}
              disabled={quickLoading}
              className="px-6 py-2.5 rounded-lg bg-emerald-500/15 text-emerald-300 font-semibold hover:bg-emerald-500/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-sm"
            >
              {quickLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              {quickLoading ? "Running Gemini snapshot…" : "Run Quick Analysis"}
            </button>
          </div>

          {quickError && (
            <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
              {quickError}
            </div>
          )}

          {quickResult && (
            <div className="mt-4 rounded-lg border border-border bg-background/60 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="font-mono">
                  {quickResult.symbol} · {quickResult.period}
                </span>
                <span>
                  {quickResult.model} · {new Date(quickResult.generated_at).toLocaleString()}
                </span>
              </div>
              <p className="text-sm leading-6 text-foreground">{quickResult.analysis}</p>
            </div>
          )}
        </div>

        {/* Symbol Input */}
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
            Run Pipeline Analysis
          </p>
          <div className="flex gap-3 items-end">
            <div className="flex-1 space-y-1.5">
              <label className="text-xs text-muted-foreground">Symbol</label>
              <input
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base font-mono uppercase focus:outline-none focus:ring-1 focus:ring-accent"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                onKeyDown={e => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void runQuickAnalysis();
                  }
                }}
                placeholder="SPY"
                maxLength={10}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Type</label>
              <div className="flex gap-2">
                <button
                  onClick={() => setIsFutures(false)}
                  className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    !isFutures
                      ? "bg-accent/20 text-accent"
                      : "bg-background border border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Equity/ETF
                </button>
                <button
                  onClick={() => setIsFutures(true)}
                  className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isFutures
                      ? "bg-accent/20 text-accent"
                      : "bg-background border border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Futures
                </button>
              </div>
            </div>
            <button
              onClick={runAnalysis}
              disabled={pipelineLoading}
              className="px-6 py-2.5 rounded-lg bg-accent/20 text-accent font-semibold hover:bg-accent/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-sm"
            >
              {pipelineLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              {pipelineLoading ? "Running 5-stage pipeline…" : "Analyze"}
            </button>
          </div>
          {pipelineLoading && (
            <div className="mt-4 text-xs text-muted-foreground space-y-1 animate-pulse">
              <p>Stage 1: Technical + News + Social + Fundamental analysts running in parallel…</p>
              <p>Stage 2: Bull/Bear debate…</p>
              <p>Stage 3–5: Trader → Risk Manager → Fund Manager…</p>
            </div>
          )}
        </div>

        {/* Error */}
        {pipelineError && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
            {pipelineError}
          </div>
        )}

        {/* Results */}
        {pipelineResult && (
          <div className="space-y-4">
            {/* Summary Card */}
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-2xl font-mono font-bold">{pipelineResult.symbol}</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {isFutures ? "Futures" : "Equity/ETF"} · 5-stage pipeline complete
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-3xl font-bold ${actionColor(pipelineResult.final_action)}`}>
                    {pipelineResult.final_action?.toUpperCase() ?? "—"}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {((pipelineResult.confidence ?? 0) * 100).toFixed(0)}% confidence
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Bull Score</span>
                    <span className="tabular-nums text-green-400">{(pipelineResult.bull_score ?? 0).toFixed(2)}</span>
                  </div>
                  {scoreBar(pipelineResult.bull_score ?? 0, "bg-green-500")}
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Bear Score</span>
                    <span className="tabular-nums text-red-400">{(pipelineResult.bear_score ?? 0).toFixed(2)}</span>
                  </div>
                  {scoreBar(pipelineResult.bear_score ?? 0, "bg-red-500")}
                </div>
              </div>

              {pipelineResult.summary && (
                <p className="mt-3 text-sm text-muted-foreground border-t border-border pt-3">
                  {pipelineResult.summary}
                </p>
              )}
            </div>

            {/* Stage Cards */}
            {(
              [
                { key: "technical", label: "Stage 1A — Technical Analyst" },
                { key: "news", label: "Stage 1B — News Analyst" },
                { key: "social", label: "Stage 1C — Social Analyst" },
                { key: "fundamental", label: "Stage 1D — Fundamental Analyst" },
                { key: "debate", label: "Stage 2 — Bull/Bear Debate" },
                { key: "trader", label: "Stage 3 — Trader Decision" },
                { key: "risk", label: "Stage 4 — Risk Manager" },
                { key: "fund_manager", label: "Stage 5 — Fund Manager" },
              ] as const
            ).map(({ key, label }) => {
              const stage = pipelineResult[key as keyof PipelineResult] as Record<string, unknown> | undefined;
              if (!stage) return null;
              const isOpen = expanded[key];
              return (
                <div key={key} className="rounded-xl border border-border bg-card overflow-hidden">
                  <button
                    className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/5 transition-colors"
                    onClick={() => toggle(key)}
                  >
                    <span className="text-sm font-medium">{label}</span>
                    <div className="flex items-center gap-2">
                      {"signal" in stage && stage.signal !== undefined && (
                        <span className={`text-xs font-mono ${actionColor(String(stage.signal))}`}>
                          {String(stage.signal).toUpperCase()}
                        </span>
                      )}
                      {"confidence" in stage && stage.confidence !== undefined && (
                        <span className="text-xs text-muted-foreground">
                          {(Number(stage.confidence) * 100).toFixed(0)}%
                        </span>
                      )}
                      {isOpen
                        ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                        : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                      }
                    </div>
                  </button>
                  {isOpen && (
                    <div className="border-t border-border px-5 py-4">
                      <pre className="text-xs text-muted-foreground overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(stage, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
