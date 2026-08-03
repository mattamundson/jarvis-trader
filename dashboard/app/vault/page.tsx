"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Archive,
  FileWarning,
  Link2,
  Lock,
  Play,
  RefreshCw,
  WifiOff,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchEngine, fetchEngineRaw, postEngine } from "@/lib/api";
import { POLL_INTERVAL } from "@/lib/polling-config";

// ── Types (mirror engine/routers/vault_router.py) ────────────────────────────
// This route is INFORMATIONAL / KNOWLEDGE-BASE ONLY, same as the router it
// talks to — it never reads or writes LIVE_TRADING_ENABLED, safety_layer.py,
// or the order path.

interface VaultStatus {
  vault_root: string;
  folder_note_counts: Record<string, number>;
  latest_reports: Record<string, string | null>;
  // e.g. { ENABLE_VAULT_SYNTHESIS: true, ENABLE_VAULT_CONTRADICTION: false, ... }
  flags: Record<string, boolean>;
}

interface JobResult {
  job: string;
  written: boolean;
  path: string | null;
  detail: string;
}

type ReportKind = "brief" | "contradictions" | "lint";

// Report kind -> (tab label, arming env flag, icon). Keep in sync with
// engine/routers/vault_router.py's _REPORTS map -- the flag names here MUST
// match exactly what the engine checks, since the whole point of surfacing
// them is that the dashboard cannot silently drift from the real gate.
const REPORT_TABS: {
  id: ReportKind;
  label: string;
  flag: string;
  icon: typeof Archive;
}[] = [
  { id: "brief", label: "Synthesis Brief", flag: "ENABLE_VAULT_SYNTHESIS", icon: Archive },
  { id: "contradictions", label: "Thesis Contradictions", flag: "ENABLE_VAULT_CONTRADICTION", icon: FileWarning },
  { id: "lint", label: "Wikilink Lint", flag: "ENABLE_VAULT_LINT", icon: Link2 },
];

function statusFetcher(): Promise<VaultStatus> {
  return fetchEngine<VaultStatus>("/vault/status");
}

export default function VaultPage() {
  const [activeTab, setActiveTab] = useState<ReportKind>("brief");
  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
    mutate: refreshStatus,
  } = useSWR<VaultStatus>("/vault/status", statusFetcher, {
    refreshInterval: POLL_INTERVAL.SLOW,
    revalidateOnFocus: false,
  });

  return (
    <div className="flex flex-col gap-6 p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Archive className="h-6 w-6 text-accent" />
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Vault</h1>
          </div>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Obsidian second-brain automations — read the overnight synthesis
            brief, thesis contradiction check, and wikilink lint reports, or
            trigger a run on demand. Knowledge-base only: this surface never
            reads or writes trading state.
          </p>
        </div>
        <button
          onClick={() => refreshStatus()}
          className="p-2 hover:bg-secondary rounded-full transition-colors shrink-0"
          title="Refresh status"
        >
          <RefreshCw className={`w-4 h-4 ${statusLoading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {statusError && (
        <div className="flex items-center gap-2 p-4 bg-bear/10 border border-bear/20 text-bear rounded-lg text-sm">
          <WifiOff className="h-4 w-4 shrink-0" />
          /vault/status unreachable — engine may be down or restarting. Not
          showing stale data.
        </div>
      )}

      {/* Status card */}
      <Card>
        <CardHeader>
          <CardTitle>Vault Status</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {status ? (
            <>
              <div className="text-xs font-mono text-muted-foreground break-all">
                {status.vault_root}
              </div>
              {Object.keys(status.folder_note_counts).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                  {Object.entries(status.folder_note_counts).map(([folder, count]) => (
                    <div key={folder} className="rounded-lg border border-border p-3">
                      <div className="text-[11px] text-muted-foreground truncate" title={folder}>
                        {folder}
                      </div>
                      <div className="text-lg font-semibold text-foreground">{count}</div>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex flex-wrap gap-2 pt-2">
                {Object.entries(status.flags).map(([flag, on]) => (
                  <Badge key={flag} variant={on ? "bull" : "neutral"} title={`${flag}=${on ? "1" : "0"}`}>
                    {flag} · {on ? "armed" : "off"}
                  </Badge>
                ))}
              </div>
            </>
          ) : (
            !statusError && (
              <div className="text-sm text-muted-foreground italic">Loading vault status…</div>
            )
          )}
        </CardContent>
      </Card>

      {/* Report tabs */}
      <div className="flex gap-1 border-b border-border">
        {REPORT_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 font-mono text-xs font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab.id
                ? "border-accent text-accent"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {REPORT_TABS.map((tab) =>
        activeTab === tab.id ? (
          <ReportPanel
            key={tab.id}
            kind={tab.id}
            label={tab.label}
            flag={tab.flag}
            armed={status ? (status.flags[tab.flag] ?? false) : null}
            latestFilename={status?.latest_reports?.[tab.id] ?? null}
          />
        ) : null
      )}
    </div>
  );
}

// ── Report panel (per report kind) ───────────────────────────────────────────

function ReportPanel({
  kind,
  label,
  flag,
  armed,
  latestFilename,
}: {
  kind: ReportKind;
  label: string;
  flag: string;
  /** null = status not loaded yet (unknown), so the run button stays disabled. */
  armed: boolean | null;
  latestFilename: string | null;
}) {
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<JobResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const {
    data: content,
    error: contentError,
    isLoading: contentLoading,
    mutate: refreshContent,
  } = useSWR<string | null>(
    `/vault/${kind}/latest`,
    async () => {
      const res = await fetchEngineRaw(`/vault/${kind}/latest`);
      // 404 = "no report written yet" -- an expected, non-error state, not a
      // fetch failure. Only a non-2xx/non-404 status is a real error.
      if (res.status === 404) return null;
      if (!res.ok) throw new Error(`/vault/${kind}/latest error ${res.status}`);
      return res.text();
    },
    { revalidateOnFocus: false }
  );

  async function handleRun() {
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    try {
      const result = await postEngine<JobResult>(`/vault/${kind}/run`);
      setRunResult(result);
      if (result.written) await refreshContent();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  // Only positively-confirmed `armed === true` enables the button -- while
  // status is still loading (`null`) or the engine says the flag is off
  // (`false`), the button stays disabled. This is the load-bearing bit: the
  // operator must never see an enabled-looking button that then 409s.
  const disabled = armed !== true || running;
  const gateReason =
    armed === false
      ? `Disabled — ${flag}=0. Set ${flag}=1 in engine/.env to arm this job.`
      : armed === null
        ? "Checking vault status…"
        : undefined;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>{label}</CardTitle>
        <div className="flex flex-col items-end gap-1">
          <Button
            size="sm"
            variant="outline"
            onClick={handleRun}
            disabled={disabled}
            title={gateReason ?? `Run ${label} now`}
          >
            {armed === false ? (
              <Lock className="h-3.5 w-3.5" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {running ? "Running…" : "Run now"}
          </Button>
          {/* Visible label, not just a hover tooltip -- an operator scanning
              the page must see WHY the button is dead without hovering. */}
          {armed === false && (
            <span className="text-[10px] font-mono text-warn text-right max-w-[240px]">
              {gateReason}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {latestFilename && (
          <div className="text-[11px] font-mono text-muted-foreground">
            Latest on disk: {latestFilename}
          </div>
        )}

        {runError && (
          <div className="flex items-center gap-2 p-3 bg-bear/10 border border-bear/20 text-bear rounded-lg text-xs">
            <WifiOff className="h-3.5 w-3.5 shrink-0" />
            {runError}
          </div>
        )}
        {runResult && (
          <div
            className={`p-3 rounded-lg text-xs border ${
              runResult.written
                ? "bg-bull/10 border-bull/20 text-bull"
                : "bg-muted border-border text-muted-foreground"
            }`}
          >
            {runResult.detail}
          </div>
        )}

        <div className="rounded-lg border border-border bg-card p-4 max-h-[60vh] overflow-y-auto">
          {contentLoading && (
            <p className="text-xs text-muted-foreground italic">Loading report…</p>
          )}
          {contentError && (
            <p className="text-xs text-muted-foreground italic">
              /vault/{kind}/latest unreachable — engine may be down or
              restarting. Not showing stale data.
            </p>
          )}
          {!contentLoading && !contentError && content === null && (
            <p className="text-xs text-muted-foreground italic">
              No {label.toLowerCase()} report found in 00-Inbox yet.
            </p>
          )}
          {content && (
            <p className="font-mono text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap">
              {content}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
