import { redirect } from "next/navigation";

// P2.1 IA consolidation: the sprawling kitchen-sink overview is dissolved in favor
// of ONE flagship command-center landing page. The root path now lands on the
// operational HUD at /command-center (the only one of the former five "now" pages
// built as a real safety-first HUD). Its widgets already live on their real homes
// (performance, discord, safety, etc.), so nothing is orphaned by this redirect.
// Remaining fold work (KPI strip from /today, Ask JARVIS from /jarvis, honesty
// badges from /trust-pane) is tracked as P2.1 sub-work for the Phase-2 draft-PR review.
export default function Home() {
  redirect("/command-center");
}
