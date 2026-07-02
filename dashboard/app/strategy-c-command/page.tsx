/**
 * Strategy C+ Command Center — unified into the main JARVIS dashboard.
 *
 * The Command Center was previously a standalone HTML file opened from disk
 * (a second "Jarvis" object). Per Amo's 2026-06-11 directive it now lives
 * inside the one dashboard: the full build is served from
 * /strategy-c-command-center.html (dashboard/public/) and embedded here
 * full-bleed, reachable from the sidebar like every other page.
 *
 * It talks to the engine (8010) and the quotes/options bridge (8020)
 * directly via 127.0.0.1 — same data plane as the rest of the dashboard.
 */
export default function StrategyCCommandPage() {
  return (
    <div className="h-[calc(100vh-1rem)] w-full">
      <iframe
        src="/strategy-c-command-center.html"
        title="JARVIS Strategy C+ Command Center"
        className="h-full w-full border-0 rounded-lg"
      />
    </div>
  );
}
