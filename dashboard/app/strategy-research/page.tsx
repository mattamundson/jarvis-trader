import { StrategyResearchPanel } from "@/components/StrategyResearchPanel";

export const metadata = {
  title: "Strategy Research · JARVIS",
};

/**
 * Strategy Research page — surfaces X-bookmark edge-scan candidates and their
 * research gate-v2 verdicts. Non-authorizing: these never route capital.
 */
export default function StrategyResearchPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto flex flex-col gap-4">
      <div>
        <h1 className="font-mono text-lg font-bold text-foreground">Strategy Research</h1>
        <p className="font-mono text-xs text-muted-foreground mt-1">
          Edge candidates mined from X.com bookmarks, backtested through the real gate-v2 battery.
          Long-biased equity edges are judged against an equity-class drawdown ceiling, not the
          intraday-futures bar — and this surface never authorizes routing.
        </p>
      </div>
      <StrategyResearchPanel />
    </div>
  );
}
