"use client";

import { useState } from "react";
import useSWR from "swr";
import { Flag } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { fetchEngine } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  description: string;
  category: FlagCategory;
  requires_restart: boolean;
}

export type FlagCategory = "ai" | "risk" | "market" | "experimental" | "security";

interface FlagsResponse {
  flags: FeatureFlag[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORY_ORDER: FlagCategory[] = ["ai", "risk", "market", "security", "experimental"];

const CATEGORY_LABELS: Record<FlagCategory, string> = {
  ai: "AI",
  risk: "Risk",
  market: "Market",
  experimental: "Experimental",
  security: "Security",
};

// Uses the project's strict badge variants: "bull" | "bear" | "warn" | "info" | "neutral"
const CATEGORY_BADGE_VARIANT: Record<FlagCategory, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  ai: "info",
  risk: "bear",
  market: "bull",
  experimental: "neutral",
  security: "warn",
};

// ── Fetcher ───────────────────────────────────────────────────────────────────

async function fetchFlags(): Promise<FlagsResponse> {
  return fetchEngine<FlagsResponse>("/flags/");
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFlagName(name: string): string {
  return name
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function groupFlagsByCategory(flags: FeatureFlag[]): Map<FlagCategory, FeatureFlag[]> {
  const map = new Map<FlagCategory, FeatureFlag[]>();
  for (const flag of flags) {
    const existing = map.get(flag.category) ?? [];
    existing.push(flag);
    map.set(flag.category, existing);
  }
  return map;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function FlagsSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      {Array.from({ length: 3 }).map((_, gi) => (
        <div key={gi} className="space-y-2">
          <div className="h-3 w-20 bg-muted rounded" />
          {Array.from({ length: 3 }).map((__, fi) => (
            <div key={fi} className="h-10 w-full bg-muted rounded-lg" />
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Flag Row ──────────────────────────────────────────────────────────────────

interface FlagRowProps {
  flag: FeatureFlag;
  onToggle: (name: string, enabled: boolean) => Promise<void>;
  pendingName: string | null;
  restartPending: Set<string>;
}

function FlagRow({ flag, onToggle, pendingName, restartPending }: FlagRowProps) {
  const isPending = pendingName === flag.name;
  const showRestartBadge = restartPending.has(flag.name);

  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 rounded-lg border px-4 py-3 transition-colors",
        flag.enabled
          ? "border-border bg-card"
          : "border-border/50 bg-muted/20"
      )}
    >
      {/* Left: name + description */}
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-foreground">
            {formatFlagName(flag.name)}
          </span>
          {showRestartBadge && (
            <Badge variant="warn" className="text-[10px] px-1.5 py-0">
              Requires restart
            </Badge>
          )}
        </div>
        {flag.description && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {flag.description}
          </p>
        )}
      </div>

      {/* Right: toggle */}
      <div className="shrink-0 mt-0.5">
        <Switch
          checked={flag.enabled}
          onCheckedChange={(enabled) => onToggle(flag.name, enabled)}
          disabled={isPending}
          aria-label={`Toggle ${formatFlagName(flag.name)}`}
        />
      </div>
    </div>
  );
}

// ── Category Section ──────────────────────────────────────────────────────────

interface CategorySectionProps {
  category: FlagCategory;
  flags: FeatureFlag[];
  onToggle: (name: string, enabled: boolean) => Promise<void>;
  pendingName: string | null;
  restartPending: Set<string>;
}

function CategorySection({
  category,
  flags,
  onToggle,
  pendingName,
  restartPending,
}: CategorySectionProps) {
  return (
    <div className="space-y-2">
      {/* Section divider header */}
      <div className="flex items-center gap-2 pb-1">
        <Badge variant={CATEGORY_BADGE_VARIANT[category]}>
          {CATEGORY_LABELS[category]}
        </Badge>
        <div className="flex-1 h-px bg-border/50" />
        <span className="text-[11px] text-muted-foreground">
          {flags.filter((f) => f.enabled).length}/{flags.length} on
        </span>
      </div>

      {/* Flag rows */}
      <div className="space-y-1.5">
        {flags.map((flag) => (
          <FlagRow
            key={flag.name}
            flag={flag}
            onToggle={onToggle}
            pendingName={pendingName}
            restartPending={restartPending}
          />
        ))}
      </div>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export function FeatureFlagsPanel() {
  const [pendingName, setPendingName] = useState<string | null>(null);
  const [restartPending, setRestartPending] = useState<Set<string>>(new Set());
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  const { data, error, isLoading, mutate } = useSWR<FlagsResponse>(
    "flags/",
    fetchFlags,
    { revalidateOnFocus: false }
  );

  async function handleToggle(name: string, enabled: boolean) {
    if (!data) return;

    // Optimistically update the local cache immediately
    const optimisticFlags = data.flags.map((f) =>
      f.name === name ? { ...f, enabled } : f
    );
    mutate({ flags: optimisticFlags }, false);

    setPendingName(name);
    setFeedback(null);

    try {
      await fetchEngine(`/flags/${name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });

      // Check if the toggled flag requires a restart
      const flag = data.flags.find((f) => f.name === name);
      if (flag?.requires_restart) {
        setRestartPending((prev) => new Set(prev).add(name));
        setFeedback({
          ok: true,
          msg: `"${formatFlagName(name)}" ${enabled ? "enabled" : "disabled"}. Engine restart required to take effect.`,
        });
      } else {
        setFeedback({
          ok: true,
          msg: `"${formatFlagName(name)}" ${enabled ? "enabled" : "disabled"}.`,
        });
      }

      // Revalidate from server to confirm
      mutate();
    } catch (err) {
      // Revert optimistic update on failure
      mutate();
      setFeedback({
        ok: false,
        msg: `Failed to update "${formatFlagName(name)}": ${err instanceof Error ? err.message : String(err)}`,
      });
    } finally {
      setPendingName(null);
    }
  }

  const grouped = data ? groupFlagsByCategory(data.flags) : null;
  const totalFlags = data?.flags.length ?? 0;
  const enabledCount = data?.flags.filter((f) => f.enabled).length ?? 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Flag className="h-4 w-4 text-accent" />
            <CardTitle>Feature Flags</CardTitle>
            {!isLoading && data && (
              <Badge variant="neutral" className="text-[10px]">
                {enabledCount}/{totalFlags} active
              </Badge>
            )}
          </div>
          <button
            onClick={() => mutate()}
            disabled={isLoading}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
          >
            {isLoading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Feedback message */}
        {feedback && (
          <p
            className={cn(
              "text-xs rounded-lg px-3 py-2",
              feedback.ok
                ? "bg-bull/10 text-bull border border-bull/20"
                : "bg-bear/10 text-bear border border-bear/20"
            )}
          >
            {feedback.msg}
          </p>
        )}

        {/* Loading skeleton */}
        {isLoading && <FlagsSkeleton />}

        {/* Error state */}
        {error && !isLoading && (
          <div className="rounded-lg bg-bear/10 border border-bear/20 px-4 py-3 text-sm text-bear space-y-1">
            <p className="font-medium">Failed to load feature flags</p>
            <p className="text-xs text-bear/80">
              {error instanceof Error ? error.message : "Engine may be offline or the /flags/ endpoint is not available."}
            </p>
          </div>
        )}

        {/* Flag groups */}
        {grouped && (
          <div className="space-y-5">
            {CATEGORY_ORDER.filter((cat) => grouped.has(cat)).map((cat) => (
              <CategorySection
                key={cat}
                category={cat}
                flags={grouped.get(cat)!}
                onToggle={handleToggle}
                pendingName={pendingName}
                restartPending={restartPending}
              />
            ))}

            {/* Uncategorized fallback — any category not in CATEGORY_ORDER */}
            {Array.from(grouped.entries())
              .filter(([cat]) => !(CATEGORY_ORDER as string[]).includes(cat))
              .map(([cat, flags]) => (
                <CategorySection
                  key={cat}
                  category={cat as FlagCategory}
                  flags={flags}
                  onToggle={handleToggle}
                  pendingName={pendingName}
                  restartPending={restartPending}
                />
              ))}
          </div>
        )}

        {/* Empty state */}
        {grouped && grouped.size === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No feature flags configured.
          </p>
        )}

        {/* Restart notice footer */}
        {restartPending.size > 0 && (
          <div className="rounded-lg bg-warn/10 border border-warn/20 px-4 py-3 text-xs text-warn space-y-1">
            <p className="font-semibold">Engine restart required</p>
            <p>
              {restartPending.size} flag{restartPending.size !== 1 ? "s" : ""} changed during this session require an engine restart to take effect.
              Run <code className="font-mono bg-warn/10 px-1 rounded">.\restart_engine.ps1</code> when ready.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
