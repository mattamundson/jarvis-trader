import { StrategyResearchPanel } from "@/components/StrategyResearchPanel";
<<<<<<< HEAD
=======
import { StrategyLabPanel } from "@/components/StrategyLabPanel";
import { EquityResearchPanel } from "@/components/EquityResearchPanel";
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

export const metadata = {
  title: "Strategy Research · JARVIS",
};

/**
 * Strategy Research page — surfaces X-bookmark edge-scan candidates and their
<<<<<<< HEAD
 * research gate-v2 verdicts. Non-authorizing: these never route capital.
 */
export default function StrategyResearchPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto flex flex-col gap-4">
=======
 * research gate-v2 verdicts, plus equity daily SMA-trend certifications and
 * forward evidence from the closed-trades ledger. Non-authorizing: these never route capital.
 */
export default function StrategyResearchPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto flex flex-col gap-6">
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
      <ExploratoryBanner what="Edge candidates here are research-gate output" />
      <div>
        <h1 className="font-mono text-lg font-bold text-foreground">Strategy Research</h1>
        <p className="font-mono text-xs text-muted-foreground mt-1">
          Edge candidates mined from X.com bookmarks, backtested through the real gate-v2 battery.
          Long-biased equity edges are judged against an equity-class drawdown ceiling, not the
<<<<<<< HEAD
          intraday-futures bar — and this surface never authorizes routing.
        </p>
      </div>
      <StrategyResearchPanel />
=======
          intraday-futures bar — and this surface never routes capital.
        </p>
      </div>
      <StrategyResearchPanel />
      <StrategyLabPanel />
      <EquityResearchPanel />
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    </div>
  );
}
