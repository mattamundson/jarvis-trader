/**
 * Strategy C+ Command Center — RETIRED 2026-07-21.
 *
 * This route used to embed /strategy-c-command-center.html (a 9,597-line
 * standalone build served from dashboard/public/). That file has been archived
 * to ~/Archive/2026/jarvis-phantom-quarantine/ because it fabricated data:
 *
 *   - Math.random() synthesized P&L deltas, IV/skew values, and gateway latency
 *     (lines 7020, 7618, 7622, 8883 of the archived file)
 *   - The gateway chip hardcoded "CONNECTED (PAPER)" regardless of IB state
 *   - A preflight panel printed a static "Port 8020 - health endpoint OK"
 *     string that was never the result of a health check
 *   - It called 127.0.0.1:8020 directly, bypassing fetchEngine/postEngine, so
 *     it was invisible to the dashboard's provenance and staleness plumbing
 *
 * Because it was .html and not .ts/.tsx, every CI guard in this repo (the
 * no-bare-fetch grep, tsc, lint) skipped it entirely. It rendered confident
 * numbers that no engine ever produced -- the exact failure mode the root
 * CLAUDE.md calls out as worse than being visibly offline.
 *
 * Do NOT restore this file. Any capability worth keeping should be rebuilt as
 * a real page in app/, fed through lib/api.ts, and provenance-tagged.
 */
import Link from "next/link";

export default function StrategyCCommandPage() {
  return (
    <div className="flex h-[calc(100vh-1rem)] w-full items-center justify-center p-6">
      <div className="max-w-xl space-y-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-6">
        <h1 className="text-lg font-semibold text-amber-400">
          Strategy C+ Console retired
        </h1>
        <p className="text-sm text-muted-foreground">
          This console was removed on 2026-07-21 because it displayed fabricated
          data. P&amp;L deltas, implied-vol figures and gateway latency were
          generated with <code className="text-amber-400">Math.random()</code>,
          and the connection badge read{" "}
          <span className="text-amber-400">CONNECTED (PAPER)</span> whether or
          not IB was reachable.
        </p>
        <p className="text-sm text-muted-foreground">
          It bypassed the engine API client, so none of it was covered by the
          dashboard&apos;s provenance or staleness checks. The original build is
          archived at{" "}
          <code className="text-xs">
            ~/Archive/2026/jarvis-phantom-quarantine/
          </code>
          .
        </p>
        <p className="text-sm">
          <Link href="/" className="text-sky-400 underline underline-offset-4">
            Return to the overview
          </Link>{" "}
          — those numbers come from the engine.
        </p>
      </div>
    </div>
  );
}
