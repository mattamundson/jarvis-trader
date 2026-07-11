import { redirect } from "next/navigation";

// P2.3 IA readiness consolidation: /strategy-ledger's per-strategy gate-v2 verdict
// table ("which candidates clear the gate now") was folded into the canonical
// /readiness promotion-gate page (rendered there via <StrategyLedgerView />). This
// former location redirects so existing bookmarks/links keep working (single hop,
// matching the /validation→/readiness, /scorecard→/readiness, /stats→/performance
// precedents).
export default function StrategyLedgerRedirect() {
  redirect("/readiness");
}
