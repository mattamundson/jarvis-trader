"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Code2, FileCode, FileText, Layers, User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchThinkScriptRegistry,
  fetchThinkScriptRegistryEntry,
  type ThinkScriptRegistryEntry,
  type ThinkScriptStatus,
} from "@/lib/api";

const REGISTRY_REFRESH_MS = 5 * 60_000; // the YAML catalog changes rarely

// Registry `status` -> badge variant. "active"/"ported" read as healthy;
// "experimental" and "reference_only" as advisory; "orphan"/"deprecated" as warn
// so a stale entry doesn't look equally trustworthy to a maintained one.
const STATUS_VARIANT: Record<ThinkScriptStatus, "bull" | "info" | "neutral" | "warn"> = {
  active: "bull",
  ported: "bull",
  experimental: "info",
  reference_only: "neutral",
  orphan: "warn",
  deprecated: "warn",
};

function fileLabel(file: string | string[]): string {
  return Array.isArray(file) ? file.join(", ") : file;
}

/**
 * Master-detail browser for the ThinkScript registry (thinkorswim-scripts/registry.yaml,
 * served via GET /thinkscript/registry). Left: filterable list of every study wired into
 * JARVIS. Right: the selected study's metadata plus its full markdown doc body
 * (GET /thinkscript/registry/{id}).
 */
export function ThinkscriptRegistry() {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ThinkScriptStatus | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, error, isLoading } = useSWR(
    "thinkscript-registry",
    fetchThinkScriptRegistry,
    { refreshInterval: REGISTRY_REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const scripts = useMemo(() => {
    const all = data?.scripts ?? [];
    const q = query.trim().toLowerCase();
    return all
      .filter((s) => statusFilter === "all" || s.status === statusFilter)
      .filter((s) => {
        if (!q) return true;
        return (
          s.id.toLowerCase().includes(q) ||
          s.layer_name.toLowerCase().includes(q) ||
          s.author.toLowerCase().includes(q) ||
          fileLabel(s.file).toLowerCase().includes(q)
        );
      })
      .sort((a, b) => a.layer - b.layer || a.id.localeCompare(b.id));
  }, [data, query, statusFilter]);

  const selected: ThinkScriptRegistryEntry | undefined = useMemo(
    () => data?.scripts.find((s) => s.id === selectedId),
    [data, selectedId]
  );

  const { data: docEntry, isLoading: docLoading } = useSWR(
    selectedId ? ["thinkscript-registry-entry", selectedId] : null,
    () => fetchThinkScriptRegistryEntry(selectedId as string),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-6 text-xs text-muted-foreground">
          Loading ThinkScript registry…
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardContent className="p-6 text-xs text-bear">
          Registry unavailable — GET /thinkscript/registry failed. The engine may not have{" "}
          <code className="font-mono">JARVIS_TRADER_SCRIPTS_PATH</code> configured, or
          <code className="font-mono"> thinkorswim-scripts/registry.yaml</code> is missing.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      {/* List */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-3.5 w-3.5" />
            Registry ({scripts.length}/{data.scripts.length})
          </CardTitle>
          <span className="font-mono text-[10px] text-muted-foreground/70">v{data.version}</span>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search id, layer, author, file…"
              className="min-w-[10rem] flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ThinkScriptStatus | "all")}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="all">all statuses</option>
              {(Object.keys(STATUS_VARIANT) as ThinkScriptStatus[]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="max-h-[520px] space-y-1.5 overflow-y-auto pr-1">
            {scripts.length === 0 && (
              <p className="py-6 text-center text-xs text-muted-foreground">
                No studies match this filter.
              </p>
            )}
            {scripts.map((s) => {
              const active = s.id === selectedId;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedId(s.id)}
                  className={`flex w-full flex-col gap-1 rounded-md border px-2.5 py-2 text-left transition-colors ${
                    active
                      ? "border-accent/40 bg-accent/10"
                      : "border-border bg-card hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-mono text-xs font-semibold text-foreground">
                      <FileCode className="h-3 w-3 text-muted-foreground/70" />
                      {s.id}
                    </span>
                    <Badge variant={STATUS_VARIANT[s.status]} className="shrink-0">
                      {s.status}
                    </Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    L{s.layer} · {s.layer_name}
                  </p>
                  <p className="flex items-center gap-1 truncate font-mono text-[10px] text-muted-foreground/70">
                    <User className="h-2.5 w-2.5 shrink-0" />
                    {s.author}
                  </p>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Doc viewer */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5" />
            Documentation
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {!selected && (
            <p className="py-10 text-center text-xs text-muted-foreground">
              Select a study from the registry to view its docs.
            </p>
          )}
          {selected && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={STATUS_VARIANT[selected.status]}>{selected.status}</Badge>
                <span className="font-mono text-xs text-muted-foreground">
                  layer {selected.layer} — {selected.layer_name}
                </span>
                {selected.panel && (
                  <span className="rounded-md border border-border bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {selected.panel} panel
                  </span>
                )}
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">File</dt>
                <dd className="font-mono text-foreground">{fileLabel(selected.file)}</dd>
                <dt className="text-muted-foreground">Author</dt>
                <dd className="font-mono text-foreground">{selected.author}</dd>
                {selected.python_counterpart && (
                  <>
                    <dt className="text-muted-foreground">Python counterpart</dt>
                    <dd className="flex items-center gap-1 font-mono text-foreground">
                      <Code2 className="h-3 w-3 text-muted-foreground/70" />
                      {selected.python_counterpart}
                    </dd>
                  </>
                )}
                {selected.jarvis_signals.length > 0 && (
                  <>
                    <dt className="text-muted-foreground">Signals</dt>
                    <dd className="flex flex-wrap gap-1">
                      {selected.jarvis_signals.map((sig) => (
                        <Badge key={sig} variant="neutral" className="font-mono">
                          {sig}
                        </Badge>
                      ))}
                    </dd>
                  </>
                )}
              </dl>

              <div className="rounded-md border border-border bg-muted/20 p-3">
                {docLoading && (
                  <p className="text-xs text-muted-foreground">Loading doc…</p>
                )}
                {!docLoading && docEntry && !docEntry.doc_markdown && (
                  <p className="text-xs text-muted-foreground">
                    No documentation file found at {selected.docs}.
                  </p>
                )}
                {!docLoading && docEntry?.doc_markdown && (
                  // Plain pre-wrap, same tradeoff as app/framing-brief/page.tsx: no
                  // react-markdown dependency exists in this dashboard today, so
                  // headers/bold render literally rather than styled.
                  <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-foreground/90">
                    {docEntry.doc_markdown}
                  </p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
