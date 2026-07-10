import { redirect } from "next/navigation";

// P2.1 IA consolidation: the second "glance" page is dissolved into the ONE flagship
// command-center HUD. Its two unique assets — the KPI strip (Trades Today / Today P&L
// / Open Positions / Val Status) and the fuller system-health checklist (data-leg vs
// exec-leg split, TradingView MCP, LLM provider chain, kill switch) — are now folded
// into /command-center, so this redirect orphans nothing. Redirects straight to the
// flagship at /command-center (the canonical entry `/` itself redirects there today),
// matching the single-hop /stats→/performance precedent.
export default function TodayRedirect() {
  redirect("/command-center");
}
