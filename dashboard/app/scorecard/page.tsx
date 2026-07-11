import { redirect } from "next/navigation";

// P2.3 IA readiness consolidation: /scorecard is promoted to the canonical /readiness
// promotion-gate page (account-level READY/APPROACHING/NOT-READY verdict + readiness
// checklist + go-live plan). Subsequent P2.3 sub-items fold /validation's gate-v2
// analytics and /strategy-ledger's per-strategy verdict table into /readiness. This
// former location redirects so existing bookmarks/links keep working (single hop,
// matching the /stats→/performance and /today→/command-center precedents).
export default function ScorecardRedirect() {
  redirect("/readiness");
}
