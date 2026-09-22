import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { loadLatestMarketBrief } from "@/lib/marketBrief/server";
import { toPublicMarketBrief, type PublicInstrumentStructure, type PublicScenario } from "@/lib/marketBrief/public";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const metadata: Metadata = {
  title: "JARVIS Market Brief",
  description: "Read-only, analysis-only market brief probability block and market-structure report.",
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

function BulletCard({ title, items }: { title: string; items: string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm text-muted-foreground">
          {items.map((item) => <li key={item} className="leading-relaxed">• {item}</li>)}
        </ul>
      </CardContent>
    </Card>
  );
}

function StructureCard({ structure }: { structure: PublicInstrumentStructure }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{structure.label} Structural Levels</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-muted-foreground">Resistance</div>
          <ul className="space-y-1 text-muted-foreground">{structure.resistance.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-muted-foreground">Support</div>
          <ul className="space-y-1 text-muted-foreground">{structure.support.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
        <div className="rounded-lg border border-border bg-background/40 p-3 text-muted-foreground">
          <p><span className="font-semibold text-foreground">Confirmation:</span> {structure.confirmation}</p>
          <p className="mt-2"><span className="font-semibold text-foreground">Invalidation:</span> {structure.invalidation}</p>
        </div>
        <p className="text-muted-foreground">{structure.bias}</p>
      </CardContent>
    </Card>
  );
}

function ScenarioCard({ scenario }: { scenario: PublicScenario }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <CardTitle>{scenario.name}</CardTitle>
          <Badge variant="static" className="font-mono">{scenario.probability.toFixed(1)}%</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-muted-foreground">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest">Conditions</div>
          <ul className="space-y-1">{scenario.conditions.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest">Targets</div>
          <ul className="space-y-1">{scenario.targets.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
        <p className="rounded-lg border border-border bg-background/40 p-3"><span className="font-semibold text-foreground">Invalidation:</span> {scenario.invalidation}</p>
      </CardContent>
    </Card>
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
  const analysis = snapshot.analysis;

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
              Public read-only market intelligence. The scorecard stays measurable; the analysis layer restores the full market-structure read without exposing trading controls.
            </p>
          </div>
          <div className="text-xs text-muted-foreground">
            Generated: <span className="font-mono text-foreground">{snapshot.generatedAt ?? "—"}</span> · {ageLabel(snapshot.ageSeconds)}
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <Stat label="Continuation" value={`${probabilities.continuation.toFixed(1)}%`} tone="text-bull" />
          <Stat label="Rotation" value={`${probabilities.rotation.toFixed(1)}%`} tone="text-warn" />
          <Stat label="Failure" value={`${probabilities.failure.toFixed(1)}%`} tone="text-bear" />
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

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <BulletCard title="Market Overview" items={analysis.marketOverview} />
          <BulletCard title="Auction Market Theory Cues" items={analysis.auctionCues} />
        </section>

        <section className="mt-4 grid gap-4 lg:grid-cols-2">
          <StructureCard structure={analysis.esStructure} />
          <StructureCard structure={analysis.nqStructure} />
        </section>

        <section className="mt-4">
          <BulletCard title="Volatility Regime" items={analysis.volatilityRegime} />
        </section>

        <section className="mt-8 space-y-4">
          <div>
            <h2 className="text-2xl font-black tracking-tight">Scenario Map</h2>
            <p className="mt-1 text-sm text-muted-foreground">Every branch is tied to explicit probabilities, conditions, targets, and invalidation.</p>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            {analysis.scenarioMap.map((scenario) => <ScenarioCard key={scenario.name} scenario={scenario} />)}
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <BulletCard title="Intraday Behavior Expectation" items={analysis.intradayPlan} />
          <BulletCard title="Final Thoughts" items={analysis.finalThoughts} />
        </section>

        {snapshot.warnings.length > 0 && (
          <section className="mt-6 rounded-xl border border-warn/40 bg-warn/5 p-4 text-sm text-warn">
            {snapshot.warnings.slice(0, 3).map((warning) => <p key={warning}>• {warning}</p>)}
          </section>
        )}

        <footer className="mt-10 border-t border-border pt-5 text-xs text-muted-foreground">
          Public contract: {snapshot.publicContract.surface} · trading controls exposed: {String(snapshot.publicContract.tradingControlsExposed)} · local path exposed: {String(snapshot.publicContract.localPathExposed)} · analysis contract: {snapshot.publicContract.analysisContract}
        </footer>
      </main>
    </div>
  );
}
