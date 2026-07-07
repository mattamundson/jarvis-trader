import { redirect } from "next/navigation";

// P2.2 IA journal-collision fix: the trade-by-trade ledger is now canonical at
// /journal (the route the sidebar "Journal" link points to). This former location
// redirects to it so existing bookmarks/links keep working. The static research
// notebook that used to live at /journal moved to /research-log; the behavioral
// analytics review remains at /journal-review (cross-linked from /journal).
export default function TradesJournalRedirect() {
  redirect("/journal");
}
