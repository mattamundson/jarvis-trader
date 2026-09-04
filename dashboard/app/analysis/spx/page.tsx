"use client";

import { ArrowLeft, FlaskConical, ScrollText } from "lucide-react";
import Link from "next/link";
import { SpxIntradayAnalysisCard } from "@/components/SpxIntradayAnalysisCard";
import { useSpxIntradayAnalysis } from "@/hooks/useSpxIntradayAnalysis";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function probability(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

/**
 * SPX deep-dive: full scenario tree + model diagnostics behind the compact
 * Mission Control card. Same read-only /api/spx-intraday snapshot; no orders,
 * no approvals, no risk mutations anywhere on this page.
 */
export default function SpxAnalysisPage() {
  const { data } = useSpxIntradayAnalysis();

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] flex items-center gap-3 px-6 py-3">
          <Link
            href="/mission-control"
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-muted-foreground hover:bg-muted"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Mission Control
          </Link>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">SPX INTRADAY ANALYSIS</h1>
            <p className="text-xs text-muted-foreground">
              Full EOD scenario tree, level ladder diagnostics, and model assumptions
            </p>
          </div>
          <Badge variant="neutral" className="ml-auto border-dashed font-mono text-[10px]">
            ANALYSIS ONLY
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-6 space-y-6">
        <SpxIntradayAnalysisCard />

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-accent">
              <FlaskConical className="h-4 w-4" /> Scenario detail
            </CardTitle>
          </CardHeader>
          <CardContent>
            {(data?.scenarios.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">
                No scenario tree available — snapshot is degraded or loading.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {data!.scenarios.map((scenario) => (
                  <div key={scenario.id} className="rounded-lg border border-border bg-background/30 p-3">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold text-foreground">{scenario.label}</span>
                      <span className="font-mono text-lg font-bold text-foreground">
                        {probability(scenario.probability)}
                      </span>
                    </div>
                    <div className="mt-1 font-mono text-xs text-muted-foreground">
                      Close band {fmt(scenario.expectedCloseBand[0])} – {fmt(scenario.expectedCloseBand[1])}
                    </div>
                    <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                      <div>
                        <span className="font-semibold text-bull">Trigger:</span> {scenario.trigger}
                      </div>
                      <div>
                        <span className="font-semibold text-bear">Invalidation:</span> {scenario.invalidation}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-accent">
              <ScrollText className="h-4 w-4" /> Model diagnostics & assumptions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-muted-foreground">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <div className="rounded-lg border border-border bg-background/30 p-2">
                <div className="text-[10px] uppercase tracking-widest">Model version</div>
                <div className="mt-1 font-mono text-foreground">{data?.modelVersion ?? "—"}</div>
              </div>
              <div className="rounded-lg border border-border bg-background/30 p-2">
                <div className="text-[10px] uppercase tracking-widest">Proxy</div>
                <div className="mt-1 font-mono text-foreground">{data?.proxyUsed ?? "—"}</div>
              </div>
              <div className="rounded-lg border border-border bg-background/30 p-2">
                <div className="text-[10px] uppercase tracking-widest">Source quality</div>
                <div className="mt-1 font-mono text-foreground">{data?.sourceQuality ?? "—"}</div>
              </div>
              <div className="rounded-lg border border-border bg-background/30 p-2">
                <div className="text-[10px] uppercase tracking-widest">Blended σ (pts)</div>
                <div className="mt-1 font-mono text-foreground">{fmt(data?.probabilityBands?.blendedSigmaPoints)}</div>
              </div>
            </div>
            <p className="leading-relaxed">
              Close probabilities use a normal approximation around the current price with a blended
              remaining-session sigma: 45% recent 1-minute realized vol, 35% VIX-implied vol, 20% fat-tail
              inflation (1.35× on the max component). Touch probabilities use the first-passage
              approximation P(touch) = 2·(1 − Φ(d/σ)) and are floored at the same-level close probability.
              Scenario weights are renormalized to 100%. All inputs are read-only market data; nothing on
              this page routes orders or modifies engine state.
            </p>
            {data && data.warnings.length > 0 && (
              <div className="rounded-lg border border-warn/30 bg-warn/5 p-2 text-warn">
                {data.warnings.map((w) => (
                  <div key={w}>{w}</div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
