import { redirect } from "next/navigation";

// P2.3 IA readiness consolidation: the standalone /stats analytics shell is folded
// into /performance (all 16 of its widgets now render there — the 10 unique ones were
// added as an "Extended Analytics" section). This former location redirects so existing
// bookmarks/links keep working.
export default function StatsRedirect() {
  redirect("/performance");
}
