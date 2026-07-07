export default function GlobalLoading() {
  return (
    <div className="min-h-screen bg-panel p-6 space-y-6">
      {/* Top nav skeleton */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Logo / title */}
          <div className="h-5 w-36 rounded-md bg-panel-border animate-pulse" />
          {/* Status pill */}
          <div className="h-4 w-20 rounded-full bg-panel-border animate-pulse" />
        </div>
        <div className="flex items-center gap-2">
          <div className="h-4 w-24 rounded-md bg-panel-border animate-pulse" />
          <div className="h-4 w-16 rounded-md bg-panel-border animate-pulse" />
        </div>
      </div>

      {/* Watchlist bar */}
      <div className="h-10 w-full rounded-lg bg-[#111827] animate-pulse border border-panel-border" />

      {/* Primary grid — 3 columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1 — Positions */}
        <SkeletonCard rows={5} height="h-48" />
        {/* Card 2 — Agent Feed */}
        <SkeletonCard rows={4} height="h-48" />
        {/* Card 3 — PnL */}
        <SkeletonCard rows={3} height="h-48" />
      </div>

      {/* Secondary grid — 2 columns */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SkeletonCard rows={6} height="h-64" />
        <SkeletonCard rows={6} height="h-64" />
      </div>

      {/* Wide bottom card */}
      <SkeletonCard rows={3} height="h-32" />

      {/* Loading label */}
      <div className="flex items-center justify-center gap-2 pt-2">
        <div className="w-1.5 h-1.5 rounded-full bg-bull animate-pulse" />
        <span className="font-mono text-xs tracking-widest text-[#333] uppercase">
          JARVIS TRADER — Loading
        </span>
        <div
          className="w-1.5 h-1.5 rounded-full bg-bull animate-pulse"
          style={{ animationDelay: "0.3s" }}
        />
      </div>
    </div>
  );
}

// Internal skeleton card component — not exported
function SkeletonCard({ rows, height }: { rows: number; height: string }) {
  return (
    <div
      className={`${height} rounded-xl border border-panel-border bg-panel-alt p-4 space-y-3 overflow-hidden`}
    >
      {/* Card header */}
      <div className="flex items-center justify-between">
        <div className="h-3.5 w-28 rounded bg-panel-border animate-pulse" />
        <div className="h-3 w-14 rounded-full bg-panel-border animate-pulse" />
      </div>
      {/* Shimmer rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-panel-border animate-pulse"
          style={{
            width: `${65 + ((i * 17) % 30)}%`,
            animationDelay: `${i * 80}ms`,
          }}
        />
      ))}
    </div>
  );
}
