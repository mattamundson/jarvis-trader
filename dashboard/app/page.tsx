import { redirect } from "next/navigation";

// P2.1 IA consolidation: the sprawling kitchen-sink overview is dissolved in favor
// of ONE flagship command-center landing page. The root path now lands on the
// operational HUD at /command-center (the only one of the former five "now" pages
// built as a real safety-first HUD). Its widgets already live on their real homes
// (performance, discord, safety, etc.), so nothing is orphaned by this redirect.
// The /today KPI strip, /jarvis Ask-JARVIS box, and /trust honesty banner are all
// folded into the flagship (P2.1); the cross-engine audit itself survives at /trust.
export default function Home() {
  redirect("/command-center");
}
