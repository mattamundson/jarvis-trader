import { StrategyResearchPanel } from "@/components/StrategyResearchPanel";
import { StrategyLabPanel } from "@/components/StrategyLabPanel";
import { EquityResearchPanel } from "@/components/EquityResearchPanel";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

export const metadata = {
  title: "Strategy Research · JARVIS",
};

/**
 * Strategy Research page — surfaces X-bookmark edge-scan candidates and their
 * research gate-v2 verdicts, plus equity daily SMA-trend certifications and
 * forward evidence from the closed-trades ledger. Non-authorizing: these never route capital.
 */
export default function StrategyResearchPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto flex flex-col gap-6">
      <ExploratoryBanner what="Edge candidates here are research-gate output" />
      <div>
        <h1 className="font-mono text-lg font-bold text-foreground">Strategy Research</h1>
        <p className="font-mono text-xs text-muted-foreground mt-1">
          Edge candidates mined from X.com bookmarks, backtested through the real gate-v2 battery.
          Long-biased equity edges are judged against an equity-class drawdown ceiling, not the
          intraday-futures bar — and this surface never routes capital.
        </p>
      </div>
      <StrategyResearchPanel />
      <StrategyLabPanel />
      <EquityResearchPanel />
    </div>
  );
}
