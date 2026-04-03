"use client";

import { useEffect } from "react";
import Link from "next/link";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    // Log to console for debugging — wire to Sentry/observability here if needed
    console.error("[JARVIS TRADER] Unhandled error boundary catch:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-6">
      <div className="w-full max-w-xl">
        {/* Header bar */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-2 h-2 rounded-full bg-[#ff4444] animate-pulse" />
          <span className="font-mono text-xs tracking-[0.3em] text-[#ff4444] uppercase">
            System Fault
          </span>
        </div>

        {/* Main card */}
        <div
          className="rounded-xl border p-6 space-y-5"
          style={{ borderColor: "#ff444433", backgroundColor: "#0f0a0a" }}
        >
          {/* Title */}
          <div className="space-y-1">
            <h1
              className="font-mono text-2xl font-bold tracking-widest uppercase"
              style={{ color: "#ff4444" }}
            >
              SYSTEM ERROR
            </h1>
            <p className="text-sm text-muted-foreground font-mono">
              An unhandled exception was caught by the global error boundary.
            </p>
          </div>

          {/* Divider */}
          <div className="h-px" style={{ backgroundColor: "#ff444422" }} />

          {/* Error message */}
          <div className="space-y-2">
            <span className="font-mono text-xs tracking-widest text-muted-foreground uppercase">
              Message
            </span>
            <pre
              className="font-mono text-sm rounded-lg p-4 overflow-x-auto leading-relaxed"
              style={{
                backgroundColor: "#0d0808",
                border: "1px solid #ff444433",
                color: "#ff8888",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {error.message || "An unknown error occurred."}
            </pre>
          </div>

          {/* Digest — only rendered if present (server-side errors include this) */}
          {error.digest && (
            <div className="space-y-2">
              <span className="font-mono text-xs tracking-widest text-muted-foreground uppercase">
                Digest
              </span>
              <p
                className="font-mono text-xs px-3 py-2 rounded"
                style={{
                  backgroundColor: "#111",
                  color: "#666",
                  border: "1px solid #1a1a2e",
                }}
              >
                {error.digest}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={reset}
              className="font-mono text-xs tracking-widest uppercase px-5 py-2.5 rounded-lg font-semibold transition-all duration-150 hover:opacity-90 active:scale-95"
              style={{
                backgroundColor: "#ff4444",
                color: "#0a0a0a",
              }}
            >
              RETRY
            </button>

            <Link
              href="/"
              className="font-mono text-xs tracking-widest uppercase px-5 py-2.5 rounded-lg font-semibold transition-all duration-150 hover:opacity-80"
              style={{
                border: "1px solid #1a1a2e",
                color: "#888",
                backgroundColor: "transparent",
              }}
            >
              RETURN HOME
            </Link>
          </div>
        </div>

        {/* Footer note */}
        <p className="mt-4 font-mono text-xs text-center" style={{ color: "#333" }}>
          JARVIS TRADER — Error Boundary v1.0
        </p>
      </div>
    </div>
  );
}
