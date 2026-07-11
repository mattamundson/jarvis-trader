import { redirect } from "next/navigation";

// P2.3 IA readiness consolidation: /journal-review is folded before redirect —
// its honest deduped metric grid + performance breakdown now render on /performance
// (JournalMetricsView), and its behavioral LLM tools (pattern analysis + formalize)
// now render on /journal's "Review" section (JournalBehaviorView). This former
// location redirects so existing bookmarks/links keep working.
export default function JournalReviewRedirect() {
  redirect("/journal");
}
