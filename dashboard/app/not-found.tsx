import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-6">
      <div className="w-full max-w-lg text-center space-y-8">
        {/* Glowing 404 */}
        <div className="relative inline-block">
          <span
            className="font-mono font-bold select-none"
            style={{
              fontSize: "clamp(5rem, 18vw, 10rem)",
              color: "#00ff88",
              opacity: 0.08,
              letterSpacing: "0.1em",
              lineHeight: 1,
            }}
          >
            404
          </span>
          <span
            className="absolute inset-0 flex items-center justify-center font-mono font-bold"
            style={{
              fontSize: "clamp(5rem, 18vw, 10rem)",
              color: "#00ff88",
              opacity: 0.9,
              letterSpacing: "0.1em",
              lineHeight: 1,
              textShadow: "0 0 40px #00ff8855, 0 0 80px #00ff8822",
            }}
          >
            404
          </span>
        </div>

        {/* Status bar */}
        <div className="flex items-center justify-center gap-2">
          <div
            className="h-px flex-1 max-w-[60px]"
            style={{ backgroundColor: "#1a1a2e" }}
          />
          <span
            className="font-mono text-xs tracking-[0.35em] uppercase"
            style={{ color: "#00ff88" }}
          >
            Route Not Found
          </span>
          <div
            className="h-px flex-1 max-w-[60px]"
            style={{ backgroundColor: "#1a1a2e" }}
          />
        </div>

        {/* Message block */}
        <div
          className="rounded-xl border p-6 space-y-3 text-left"
          style={{ borderColor: "#1a1a2e", backgroundColor: "#0d0d1a" }}
        >
          <p className="font-mono text-xs tracking-widest text-muted-foreground uppercase">
            System Response
          </p>
          <p className="font-mono text-lg font-semibold" style={{ color: "#e2e8f0" }}>
            404 — ROUTE NOT FOUND
          </p>
          <p className="font-mono text-sm text-muted-foreground leading-relaxed">
            This endpoint does not exist in the trading system.
          </p>
          <p className="font-mono text-xs" style={{ color: "#333" }}>
            Verify the URL and try again, or return to the main dashboard.
          </p>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/"
            className="font-mono text-xs tracking-widest uppercase px-6 py-3 rounded-lg font-semibold transition-all duration-150 hover:opacity-90 active:scale-95 inline-flex items-center gap-2"
            style={{
              backgroundColor: "#00ff88",
              color: "#0a0a0a",
            }}
          >
            <span className="text-base leading-none">&#8592;</span>
            RETURN TO DASHBOARD
          </Link>
        </div>

        {/* Footer */}
        <p className="font-mono text-xs" style={{ color: "#222" }}>
          JARVIS TRADER — Autonomous Trading System
        </p>
      </div>
    </div>
  );
}
