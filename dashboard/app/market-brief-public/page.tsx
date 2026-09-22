import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { loadLatestMarketBrief } from "@/lib/marketBrief/server";
import { toPublicMarketBrief } from "@/lib/marketBrief/public";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const metadata: Metadata = {
  title: "JARVIS Market Brief",
  description: "Read-only, analysis-only market brief probability block.",
};

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function pct(n: number | null | undefined, dp = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(dp)}%`;
}

function ageLabel(ageSeconds: number | null | undefined): string {
  if (ageSeconds == null || Number.isNaN(ageSeconds)) return "age unknown";
  if (ageSeconds < 60) return `${ageSeconds}s old`;
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `${minutes}m old`;
  const hours = ageSeconds / 3600;
  return `${hours.toFixed(hours >= 10 ? 0 : 1)}h old`;
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-background/50 p-4">
      <div className="text-[11px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

export default async function PublicMarketBriefPage() {
  const snapshot = toPublicMarketBrief(await loadLatestMarketBrief());
  const probabilities = snapshot.scores.probabilities;
  const conditional = snapshot.scores.conditional_diagnostic;
  const walkforward = snapshot.scores.probability_source?.walkforward;
  const es = snapshot.symbols["ES=F"];
  const nq = snapshot.symbols["NQ=F"];
  const spy = snapshot.symbols.SPY;
  const qqq = snapshot.symbols.QQQ;
  const vix = snapshot.symbols["^VIX"];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="mx-auto max-w-6xl px-5 py-8 md:py-12">
        <header className="mb-8 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral" className="font-mono">ANALYSIS ONLY</Badge>
            <Badge variant="static" className="font-mono">BASE RATE</Badge>
            <Badge variant={snapshot.sourceQuality === "fresh" ? "live" : snapshot.sourceQuality === "stale" ? "warn" : "static"} className="font-mono">
              {snapshot.sourceQuality.toUpperCase()}
            </Badge>
          </div>
          <div>
            <h1 className="text-3xl font-black tracking-tight md:text-5xl">JARVIS Market Brief</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground md:text-base">
              Public read-only market intelligence. The published probability block is the trailing ES base rate;
              state conditioning is shown only as a provisional diagnostic because walk-forward testing found no measurable edge.
            </p>
          </div>
          <div className="text-xs text-muted-foreground">
            Generated: <span className="font-mono text-foreground">{snapshot.generatedAt ?? "—"}</span> · {ageLabel(snapshot.ageSeconds)}
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <Stat label="Continuation" value={`${probabilities.continuation.toFixed(1)}%`} tone="text-bear" />
          <Stat label="Rotation" value={`${probabilities.rotation.toFixed(1)}%`} tone="text-warn" />
          <Stat label="Failure" value={`${probabilities.failure.toFixed(1)}%`} tone="text-bull" />
        </section>

        <section className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <Card>
            <CardHeader>
              <CardTitle>Probability contract</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                Primary source: <span className="font-mono text-foreground">trailing_unconditional_base_rate</span>.
                The block sums to 100.0 and is scored prospectively by the daily ledger.
              </p>
              <p>
                Walk-forward check: n=<span className="font-mono text-foreground">{walkforward?.n ?? "—"}</span>,
                model-vs-base Δ=<span className="font-mono text-foreground">{fmt(walkforward?.paired_diff_base_minus_model, 6)}</span>,
                CI=<span className="font-mono text-foreground">{walkforward?.paired_ci95?.join(" to ") ?? "—"}</span>,
                beats base=<span className="font-mono text-foreground">{String(walkforward?.model_beats_base ?? false)}</span>.
              </p>
              <p className="rounded-lg border border-border bg-background/40 p-3">
                No order routing, no broker access, no risk config, no kill-switch, no account data.
              </p>
            </CardContent>
          </Card>

          <Card className="border-warn/40 bg-warn/5">
            <CardHeader>
              <CardTitle>Conditional diagnostic</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Badge variant="warn" className="font-mono">NO MEASURED EDGE</Badge>
              <div className="grid grid-cols-2 gap-3 pt-2">
                <Stat label="State" value={conditional?.state ?? "—"} />
                <Stat label="State n" value={conditional?.n == null ? "—" : String(conditional.n)} />
                <Stat label="State cont." value={conditional?.probabilities ? `${conditional.probabilities.continuation.toFixed(1)}%` : "—"} />
                <Stat label="Publish edge" value={conditional?.publish_as_edge ? "YES" : "NO"} tone={conditional?.publish_as_edge ? "text-bull" : "text-warn"} />
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="mt-6 grid gap-4 md:grid-cols-5">
          <Stat label="ES close" value={fmt(es?.daily?.last_close)} />
          <Stat label="NQ close" value={fmt(nq?.daily?.last_close)} />
          <Stat label="SPY gap" value={pct(spy?.gap_pct, 2)} />
          <Stat label="QQQ gap" value={pct(qqq?.gap_pct, 2)} />
          <Stat label="VIX Δ" value={pct(vix?.gap_pct, 2)} />
        </section>

        {snapshot.warnings.length > 0 && (
          <section className="mt-6 rounded-xl border border-warn/40 bg-warn/5 p-4 text-sm text-warn">
            {snapshot.warnings.slice(0, 3).map((warning) => <p key={warning}>• {warning}</p>)}
          </section>
        )}

        <footer className="mt-10 border-t border-border pt-5 text-xs text-muted-foreground">
          Public contract: {snapshot.publicContract.surface} · trading controls exposed: {String(snapshot.publicContract.tradingControlsExposed)} · local path exposed: {String(snapshot.publicContract.localPathExposed)}
        </footer>
      </main>
    </div>
  );
}
