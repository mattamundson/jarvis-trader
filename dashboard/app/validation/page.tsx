import { redirect } from "next/navigation";

// P2.3 IA readiness consolidation: /validation's gate-v2 analytics (significance /
// monte-carlo / sensitivity), phase roadmap, simulate-trade, and the rest of its
// validation surface were folded into the canonical /readiness promotion-gate page
// (rendered there via <ValidationView />). This former location redirects so existing
// bookmarks/links keep working (single hop, matching the /scorecard→/readiness and
// /stats→/performance precedents).
export default function ValidationRedirect() {
  redirect("/readiness");
}
