"use client";

import React, { useState } from "react";
import { Activity, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";

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
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const runAnalysis = async () => {
    if (!symbol.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await fetchEngine<PipelineResult>("/pipeline/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: symbol.toUpperCase(), is_futures: isFutures }),
      });
      setResult(data);
      // Auto-expand top sections
      setExpanded({ technical: true, debate: true, trader: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline failed");
    } finally {
      setLoading(false);
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
            <a href="/" className="hover:text-foreground transition-colors">← Dashboard</a>
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-6 space-y-6">
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
                onChange={e => setSymbol(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === "Enter" && runAnalysis()}
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
              disabled={loading}
              className="px-6 py-2.5 rounded-lg bg-accent/20 text-accent font-semibold hover:bg-accent/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-sm"
            >
              {loading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              {loading ? "Running 5-stage pipeline…" : "Analyze"}
            </button>
          </div>
          {loading && (
            <div className="mt-4 text-xs text-muted-foreground space-y-1 animate-pulse">
              <p>Stage 1: Technical + News + Social + Fundamental analysts running in parallel…</p>
              <p>Stage 2: Bull/Bear debate…</p>
              <p>Stage 3–5: Trader → Risk Manager → Fund Manager…</p>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Summary Card */}
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-2xl font-mono font-bold">{result.symbol}</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {isFutures ? "Futures" : "Equity/ETF"} · 5-stage pipeline complete
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-3xl font-bold ${actionColor(result.final_action)}`}>
                    {result.final_action?.toUpperCase() ?? "—"}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {((result.confidence ?? 0) * 100).toFixed(0)}% confidence
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Bull Score</span>
                    <span className="tabular-nums text-green-400">{(result.bull_score ?? 0).toFixed(2)}</span>
                  </div>
                  {scoreBar(result.bull_score ?? 0, "bg-green-500")}
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Bear Score</span>
                    <span className="tabular-nums text-red-400">{(result.bear_score ?? 0).toFixed(2)}</span>
                  </div>
                  {scoreBar(result.bear_score ?? 0, "bg-red-500")}
                </div>
              </div>

              {result.summary && (
                <p className="mt-3 text-sm text-muted-foreground border-t border-border pt-3">
                  {result.summary}
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
              const stage = result[key as keyof PipelineResult] as Record<string, unknown> | undefined;
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
