import { redirect } from "next/navigation";

// P2.1 IA consolidation: the "JARVIS Command Center" page is dissolved into the ONE
// flagship command-center HUD. Its assets were folded first (no functionality dropped):
//   - Ask JARVIS NL box  -> flagship /command-center (hero utility)
//   - Regime Pulse / bookmark themes+feed / QuantStats tearsheet / Risk Attribution /
//     Discord Briefing / Action Queue -> /discord "JARVIS Intel" tab
//     (components/jarvis-intel/JarvisIntel.tsx)
//   - the hero status strip was a duplicate of the flagship + /discord headers.
// So this redirect orphans nothing. Single-hop to the flagship, matching the
// /today->/command-center and /stats->/performance redirect-stub precedent.
export default function JarvisRedirect() {
  redirect("/command-center");
}
