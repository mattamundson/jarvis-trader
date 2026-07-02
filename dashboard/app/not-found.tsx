import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-panel flex items-center justify-center p-6">
      <div className="w-full max-w-lg text-center space-y-8">
        {/* Glowing 404 */}
        <div className="relative inline-block">
          <span
            className="font-mono font-bold select-none text-bull opacity-[0.08] tracking-[0.1em] leading-none"
            style={{ fontSize: "clamp(5rem, 18vw, 10rem)" }}
          >
            404
          </span>
          <span
            className="absolute inset-0 flex items-center justify-center font-mono font-bold text-bull opacity-90 tracking-[0.1em] leading-none"
            style={{
              fontSize: "clamp(5rem, 18vw, 10rem)",
              textShadow: "0 0 40px #22c55e55, 0 0 80px #22c55e22",
            }}
          >
            404
          </span>
        </div>

        {/* Status bar */}
        <div className="flex items-center justify-center gap-2">
          <div className="h-px flex-1 max-w-[60px] bg-panel-border" />
          <span className="font-mono text-xs tracking-[0.35em] uppercase text-bull">
            Route Not Found
          </span>
          <div className="h-px flex-1 max-w-[60px] bg-panel-border" />
        </div>

        {/* Message block */}
        <div className="rounded-xl border border-panel-border bg-panel-alt p-6 space-y-3 text-left">
          <p className="font-mono text-xs tracking-widest text-muted-foreground uppercase">
            System Response
          </p>
          <p className="font-mono text-lg font-semibold text-[#e2e8f0]">
            404 — ROUTE NOT FOUND
          </p>
          <p className="font-mono text-sm text-muted-foreground leading-relaxed">
            This endpoint does not exist in the trading system.
          </p>
          <p className="font-mono text-xs text-[#333]">
            Verify the URL and try again, or return to the main dashboard.
          </p>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/"
            className="font-mono text-xs tracking-widest uppercase px-6 py-3 rounded-lg font-semibold transition-all duration-150 hover:opacity-90 active:scale-95 inline-flex items-center gap-2 bg-bull text-panel"
          >
            <span className="text-base leading-none">&#8592;</span>
            RETURN TO DASHBOARD
          </Link>
        </div>

        {/* Footer */}
        <p className="font-mono text-xs text-[#222]">
          JARVIS TRADER — Autonomous Trading System
        </p>
      </div>
    </div>
  );
}
