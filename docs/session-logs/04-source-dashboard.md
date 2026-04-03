# Dashboard Source Code — All New TSX Components

> **Note**: `ContextManagementWidget.tsx` was planned but never created.


### `dashboard/components/FeatureFlagsPanel.tsx`
```tsx
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

```

### `dashboard/components/PipelineTaskBoard.tsx`
```tsx
"use client"
import useSWR from "swr"

const fetcher = (url: string) => fetch(url).then(r => r.json())

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-zinc-700 text-zinc-400",
  running: "bg-blue-500/20 text-blue-400 animate-pulse",
  done: "bg-green-500/20 text-green-400",
  error: "bg-red-500/20 text-red-400",
  skipped: "bg-zinc-600 text-zinc-500",
}

export function PipelineTaskBoard() {
  const { data } = useSWR("http://localhost:8010/pipeline/board", fetcher, {
    refreshInterval: 2000,
  })

  if (!data?.run_id) {
    return (
      <div className="rounded-lg border border-zinc-800 p-4">
        <p className="text-sm text-zinc-500">No pipeline run in progress.</p>
      </div>
    )
  }

  const stages = Object.values(data.stages || {}) as any[]

  return (
    <div className="rounded-lg border border-zinc-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">Pipeline Board</h3>
        <span className="text-xs text-zinc-500">{data.symbol} {data.interval}</span>
      </div>
      <div className="space-y-1">
        {stages.map((t: any) => (
          <div key={t.stage} className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded font-mono ${STATUS_COLORS[t.status] ?? ""}`}>
              {t.status}
            </span>
            <span className="text-xs text-zinc-400 flex-1">{t.stage.replace(/_/g, " ")}</span>
            {t.duration_ms && (
              <span className="text-xs text-zinc-600">{t.duration_ms.toFixed(0)}ms</span>
            )}
          </div>
        ))}
      </div>
      <div className="text-xs text-zinc-500">
        {data.done_count}/{data.total_stages} complete &middot; {data.overall}
      </div>
    </div>
  )
}

```

### `dashboard/app/config/page.tsx`
```tsx
"use client";

import { useState, useEffect } from "react";
import { fetchEngine } from "@/lib/api";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Settings,
  Shield,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────

interface ConfigItem {
  key: string;
  value: string | number | boolean | string[] | null;
  sensitive: boolean;
}

interface ConfigData {
  categories: Record<string, ConfigItem[]>;
  total_fields: number;
}

interface HealthData {
  configured: Record<string, boolean>;
  live_trading_enabled: boolean;
  require_human_approval: boolean;
  paper_trading: boolean;
}

// ── Category metadata ─────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<string, { label: string; description: string }> = {
  safety: { label: "Safety Controls", description: "Position limits, circuit breakers, halt rules" },
  trading: { label: "Trading Mode", description: "Paper/live mode, capital, watchlists" },
  broker: { label: "Broker", description: "IB Gateway and Schwab connection settings" },
  data: { label: "Market Data", description: "Polygon, Finnhub, Alpaca data sources" },
  notifications: { label: "Notifications", description: "Twilio WhatsApp alert credentials" },
  llm: { label: "LLM / AI", description: "Anthropic API, model selection" },
  databases: { label: "Databases", description: "PostgreSQL, Redis, QuestDB" },
  scheduling: { label: "Scheduling", description: "Scan intervals and timers" },
  feature_flags: { label: "Feature Flags", description: "Enable/disable engine modules" },
  logging: { label: "Logging", description: "Log level and verbosity" },
  other: { label: "Other", description: "Uncategorised settings" },
};

// ── Helpers ───────────────────────────────────────────────────────────────

function formatValue(item: ConfigItem): string {
  if (item.value === null || item.value === undefined) return "not set";
  if (Array.isArray(item.value)) return item.value.join(", ");
  return String(item.value);
}

function ValueBadge({ item }: { item: ConfigItem }) {
  const display = formatValue(item);

  if (item.sensitive) {
    return (
      <span className="text-xs font-mono text-zinc-600 dark:text-zinc-500">
        {display}
      </span>
    );
  }

  if (item.value === true) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
        enabled
      </span>
    );
  }

  if (item.value === false) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-zinc-500/10 text-zinc-400 border border-zinc-600/30">
        <span className="w-1.5 h-1.5 rounded-full bg-zinc-500" />
        disabled
      </span>
    );
  }

  return (
    <span className="text-xs font-mono text-zinc-300">
      {display}
    </span>
  );
}

// ── Config Category Card ──────────────────────────────────────────────────

function CategoryCard({
  category,
  items,
}: {
  category: string;
  items: ConfigItem[];
}) {
  const [expanded, setExpanded] = useState(
    // Expand safety and feature_flags by default
    category === "safety" || category === "feature_flags" || category === "trading"
  );

  const meta = CATEGORY_LABELS[category] ?? { label: category, description: "" };
  const sensitiveCount = items.filter((i) => i.sensitive).length;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-zinc-800/40 transition-colors"
      >
        <div className="flex items-center gap-3 text-left">
          <div>
            <p className="text-sm font-semibold text-zinc-200">{meta.label}</p>
            <p className="text-[11px] text-zinc-500">{meta.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-[11px] text-zinc-500">
            {items.length} field{items.length !== 1 ? "s" : ""}
            {sensitiveCount > 0 && (
              <span className="ml-1 text-zinc-600">· {sensitiveCount} masked</span>
            )}
          </span>
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-zinc-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-zinc-500" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-4 pt-1 border-t border-zinc-800/60">
          <div className="space-y-0">
            {items.map((item) => (
              <div
                key={item.key}
                className="flex items-start justify-between py-1.5 border-b border-zinc-800/40 last:border-0 gap-4"
              >
                <span className="text-xs font-mono text-zinc-400 shrink-0">
                  {item.key}
                </span>
                <ValueBadge item={item} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── API Key Status Card ───────────────────────────────────────────────────

function ApiKeyStatusCard({ health }: { health: HealthData }) {
  const allConfigured = Object.values(health.configured).every(Boolean);
  const configuredCount = Object.values(health.configured).filter(Boolean).length;
  const totalCount = Object.values(health.configured).length;

  return (
    <div
      className={`rounded-xl border p-5 space-y-4 ${
        allConfigured
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-amber-500/30 bg-amber-500/5"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {allConfigured ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-amber-400" />
          )}
          <p className="text-sm font-semibold text-zinc-200">API Key Status</p>
        </div>
        <span
          className={`text-xs font-semibold ${
            allConfigured ? "text-emerald-400" : "text-amber-400"
          }`}
        >
          {configuredCount}/{totalCount} configured
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {Object.entries(health.configured).map(([key, ok]) => (
          <div key={key} className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                ok ? "bg-emerald-400" : "bg-red-400"
              }`}
            />
            <span className="text-[11px] text-zinc-400 truncate">
              {key.replace(/_/g, " ").toLowerCase()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Safety Posture Banner ─────────────────────────────────────────────────

function SafetyPostureBanner({ health }: { health: HealthData }) {
  const isLive = health.live_trading_enabled;
  const isPaper = health.paper_trading;

  return (
    <div
      className={`rounded-xl border p-4 flex items-center gap-4 ${
        isLive
          ? "border-red-500/40 bg-red-500/5"
          : "border-emerald-500/30 bg-emerald-500/5"
      }`}
    >
      <Shield className={`h-6 w-6 shrink-0 ${isLive ? "text-red-400" : "text-emerald-400"}`} />
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-bold ${isLive ? "text-red-300" : "text-emerald-300"}`}>
          {isLive ? "LIVE TRADING ENABLED" : "Paper Trading Mode"}
        </p>
        <p className="text-xs text-zinc-400 mt-0.5">
          {isLive
            ? "Real money orders will be submitted to the broker"
            : "All orders are simulated — no real broker fills"}
          {isPaper && !isLive && " · PAPER_TRADING=True"}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {health.require_human_approval && (
          <span className="rounded-full px-2.5 py-1 text-[10px] font-semibold bg-blue-500/10 border border-blue-500/20 text-blue-400">
            APPROVAL REQUIRED
          </span>
        )}
        {!health.require_human_approval && (
          <span className="rounded-full px-2.5 py-1 text-[10px] font-semibold bg-amber-500/10 border border-amber-500/20 text-amber-400">
            AUTO-TRADE
          </span>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function ConfigPage() {
  const [data, setData] = useState<ConfigData | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [configData, healthData] = await Promise.all([
        fetchEngine<ConfigData>("/config/overview"),
        fetchEngine<HealthData>("/config/health-check"),
      ]);
      setData(configData);
      setHealth(healthData);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/95 backdrop-blur">
        <div className="mx-auto max-w-[1200px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-zinc-100 tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-zinc-500">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Dashboard"],
                ["/analysis", "Analysis"],
                ["/backtest", "Backtest"],
                ["/performance", "Performance"],
                ["/validation", "Validation"],
                ["/journal", "Journal"],
                ["/settings", "Settings"],
                ["/health", "Health"],
                ["/config", "Config"],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className={`text-xs transition-colors ${
                    href === "/config"
                      ? "text-zinc-100 font-semibold border-b border-accent pb-0.5"
                      : "text-zinc-500 hover:text-zinc-200"
                  }`}
                >
                  {label}
                </a>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="text-[11px] text-zinc-600">
                {lastRefresh.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1200px] px-6 py-6 space-y-6">
        {/* Page title */}
        <div className="flex items-center gap-3">
          <Settings className="h-5 w-5 text-zinc-500" />
          <div>
            <h2 className="text-lg font-bold text-zinc-100">Configuration Overview</h2>
            <p className="text-xs text-zinc-500">
              {data
                ? `${data.total_fields} settings loaded — sensitive values masked`
                : "All TradingConfig fields grouped by category"}
            </p>
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 flex items-center gap-3">
            <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-red-300">Engine offline</p>
              <p className="text-xs text-zinc-400 mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !data && (
          <div className="space-y-4 animate-pulse">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-16 rounded-xl bg-zinc-800/40" />
            ))}
          </div>
        )}

        {/* Safety posture banner */}
        {health && <SafetyPostureBanner health={health} />}

        {/* API Key Status */}
        {health && <ApiKeyStatusCard health={health} />}

        {/* Category cards */}
        {data && (
          <div className="space-y-3">
            {Object.entries(data.categories).map(([category, items]) => (
              <CategoryCard key={category} category={category} items={items} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

```

### `dashboard/app/kairos/page.tsx`
```tsx
"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Eye,
  Radio,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine, postEngine } from "@/lib/api";
import { KairosObservationFeed } from "@/components/KairosObservationFeed";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KairosStatus {
  enabled: boolean;
  running: boolean;
  tick_count: number;
  watcher_count: number;
  last_tick: string | null;
  uptime_seconds: number | null;
  error_count: number;
}

interface KairosWatcher {
  name: string;
  enabled: boolean;
  hit_count_today: number;
  warning_count_today: number;
  critical_count_today: number;
  last_observation: string | null;
}

interface WatchersResponse {
  watchers: KairosWatcher[];
}

interface DreamSeverityCounts {
  info: number;
  warning: number;
  critical: number;
}

interface DreamTopWatcher {
  watcher: string;
  count: number;
}

interface DreamSummary {
  date: string;
  total_observations: number;
  severity_counts: DreamSeverityCounts;
  top_watchers: DreamTopWatcher[];
  insights: string | null;
  generated_at: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch {
    return "unknown";
  }
}

function getYesterdayDateStr(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().split("T")[0];
}

function getTodayDateStr(): string {
  return new Date().toISOString().split("T")[0];
}

// ── Watcher Card ──────────────────────────────────────────────────────────────

function WatcherCard({ watcher }: { watcher: KairosWatcher }) {
  const hasCritical = watcher.critical_count_today > 0;
  const hasWarning = watcher.warning_count_today > 0;

  const borderClass = !watcher.enabled
    ? "border-border bg-muted/30"
    : hasCritical
    ? "border-bear/30 bg-bear/5"
    : hasWarning
    ? "border-warn/30 bg-warn/5"
    : watcher.hit_count_today > 0
    ? "border-bull/20 bg-bull/5"
    : "border-border bg-card";

  const statusVariant: "bull" | "bear" | "warn" | "neutral" = !watcher.enabled
    ? "neutral"
    : hasCritical
    ? "bear"
    : hasWarning
    ? "warn"
    : "bull";

  const statusLabel = !watcher.enabled
    ? "Disabled"
    : hasCritical
    ? "Critical"
    : hasWarning
    ? "Warning"
    : watcher.hit_count_today > 0
    ? "Active"
    : "Quiet";

  return (
    <div className={`rounded-xl border p-3 space-y-2 ${borderClass}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Eye className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <p className="text-xs font-semibold text-foreground truncate">{watcher.name}</p>
        </div>
        <Badge variant={statusVariant}>{statusLabel}</Badge>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
        <span>{watcher.hit_count_today} hits</span>
        {watcher.warning_count_today > 0 && (
          <span className="text-warn">{watcher.warning_count_today} warn</span>
        )}
        {watcher.critical_count_today > 0 && (
          <span className="text-bear">{watcher.critical_count_today} crit</span>
        )}
        <span className="ml-auto">{timeAgo(watcher.last_observation)}</span>
      </div>
    </div>
  );
}

// ── Dream Summary Accordion ───────────────────────────────────────────────────

function DreamAccordion({
  label,
  dream,
  defaultOpen = false,
}: {
  label: string;
  dream: DreamSummary | null | undefined;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-semibold text-foreground">{label}</span>
          {dream && (
            <Badge variant="neutral">{dream.total_observations} obs</Badge>
          )}
        </div>
        {dream?.date && (
          <span className="text-xs text-muted-foreground">{dream.date}</span>
        )}
      </button>

      {open && (
        <div className="p-4 space-y-4 bg-card">
          {!dream ? (
            <p className="text-sm text-muted-foreground text-center py-2">
              No dream summary available for this period.
            </p>
          ) : (
            <>
              {/* Severity breakdown */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Severity Breakdown
                </p>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg bg-info/10 border border-info/20 py-2">
                    <p className="text-info font-semibold text-base font-mono">
                      {dream.severity_counts.info}
                    </p>
                    <p className="text-muted-foreground">Info</p>
                  </div>
                  <div className="rounded-lg bg-warn/10 border border-warn/20 py-2">
                    <p className="text-warn font-semibold text-base font-mono">
                      {dream.severity_counts.warning}
                    </p>
                    <p className="text-muted-foreground">Warning</p>
                  </div>
                  <div className="rounded-lg bg-bear/10 border border-bear/20 py-2">
                    <p className="text-bear font-semibold text-base font-mono">
                      {dream.severity_counts.critical}
                    </p>
                    <p className="text-muted-foreground">Critical</p>
                  </div>
                </div>
              </div>

              {/* Top watchers */}
              {dream.top_watchers.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Top Watchers
                  </p>
                  <div className="space-y-1">
                    {dream.top_watchers.map((tw) => (
                      <div
                        key={tw.watcher}
                        className="flex items-center justify-between text-xs py-1 border-b border-border/50 last:border-0"
                      >
                        <span className="text-foreground font-medium">{tw.watcher}</span>
                        <Badge variant="neutral">{tw.count} hits</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* LLM insights */}
              {dream.insights && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    LLM Insights
                  </p>
                  <div className="rounded-lg bg-muted/40 border border-border p-3">
                    <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono">
                      {dream.insights}
                    </p>
                  </div>
                </div>
              )}

              {dream.generated_at && (
                <p className="text-[11px] text-muted-foreground text-right">
                  Generated {timeAgo(dream.generated_at)}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function KairosPage() {
  const [tickLoading, setTickLoading] = useState(false);
  const [tickResult, setTickResult] = useState<string | null>(null);

  const yesterday = getYesterdayDateStr();
  const today = getTodayDateStr();

  // SWR hooks
  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
    mutate: mutateStatus,
  } = useSWR<KairosStatus>("/kairos/status", fetcher, { refreshInterval: 30_000 });

  const {
    data: watchersData,
    error: watchersError,
    isLoading: watchersLoading,
  } = useSWR<WatchersResponse>("/kairos/watchers", fetcher, { refreshInterval: 30_000 });

  const { data: yesterdayDream } = useSWR<DreamSummary>(
    `/kairos/dream/${yesterday}`,
    fetcher,
    { revalidateOnFocus: false }
  );

  const { data: todayDream } = useSWR<DreamSummary>(
    `/kairos/dream/${today}`,
    fetcher,
    { refreshInterval: 300_000 }
  );

  const watchers = watchersData?.watchers ?? [];

  // Manual tick handler
  const handleManualTick = useCallback(async () => {
    setTickLoading(true);
    setTickResult(null);
    try {
      await postEngine("/kairos/tick");
      setTickResult("Tick triggered successfully");
      mutateStatus();
    } catch (e) {
      setTickResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTickLoading(false);
    }
  }, [mutateStatus]);

  // Disabled state
  const isDisabled = status?.enabled === false;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Dashboard</a>
              <a href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Analysis</a>
              <a href="/paper" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Paper</a>
              <a href="/health" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Health</a>
              <a href="/settings" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Settings</a>
              <a href="/kairos" className="text-xs text-foreground font-semibold border-b border-accent pb-0.5">KAIROS</a>
              <a href="/config" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Config</a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {status && (
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  {status.running && status.enabled ? (
                    <>
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-bull" />
                    </>
                  ) : (
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground" />
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  {status.enabled ? (status.running ? "Running" : "Stopped") : "Disabled"}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1400px] px-6 py-6 space-y-6">
        {/* Page title */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
              <Radio className="h-6 w-6 text-accent" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-foreground tracking-tight">KAIROS Monitor</h2>
              <p className="text-xs text-muted-foreground">
                Continuous market observation daemon — watchers, observations, and dream summaries
              </p>
            </div>
          </div>

          {/* Status badge */}
          {status && (
            <Badge
              variant={
                !status.enabled ? "neutral" : status.running ? "bull" : "warn"
              }
            >
              <span className="flex items-center gap-1.5">
                {status.enabled && status.running ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : status.enabled ? (
                  <AlertTriangle className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {!status.enabled ? "KAIROS DISABLED" : status.running ? "RUNNING" : "STOPPED"}
              </span>
            </Badge>
          )}
        </div>

        {/* KAIROS disabled banner */}
        {isDisabled && !statusLoading && (
          <div className="rounded-xl border border-warn/30 bg-warn/5 p-6 text-center space-y-2">
            <AlertTriangle className="h-8 w-8 text-warn mx-auto" />
            <p className="text-sm font-semibold text-warn">KAIROS is disabled</p>
            <p className="text-xs text-muted-foreground">
              Enable KAIROS via{" "}
              <a href="/settings" className="underline text-accent hover:text-accent/80">
                Settings &rsaquo; Feature Flags
              </a>{" "}
              to start receiving market observations.
            </p>
          </div>
        )}

        {/* Engine unreachable */}
        {statusError && !statusLoading && (
          <div className="rounded-xl border border-bear/30 bg-bear/5 p-6 text-center space-y-2">
            <XCircle className="h-8 w-8 text-bear mx-auto" />
            <p className="text-sm font-semibold text-bear">Engine unreachable</p>
            <p className="text-xs text-muted-foreground">
              Could not fetch /kairos/status — verify the engine is running on port 8010
            </p>
          </div>
        )}

        {/* Main 2-column grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Observation Feed (2/3) */}
          <div className="lg:col-span-2">
            <KairosObservationFeed minutes={60} />
          </div>

          {/* Right: Status + Watchers (1/3) */}
          <div className="space-y-4">
            {/* Status Card */}
            <Card>
              <CardHeader>
                <CardTitle>System Status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {statusLoading && !status && (
                  <div className="space-y-2 animate-pulse">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-8 rounded-lg bg-muted" />
                    ))}
                  </div>
                )}

                {status && (
                  <>
                    {/* Status rows */}
                    <div className="space-y-2 text-xs">
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Enabled</span>
                        <Badge variant={status.enabled ? "bull" : "neutral"}>
                          {status.enabled ? "Yes" : "No"}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Running</span>
                        <Badge variant={status.running ? "bull" : "warn"}>
                          {status.running ? "Yes" : "No"}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Ticks today</span>
                        <span className="font-mono font-semibold text-foreground">
                          {status.tick_count}
                        </span>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground">Watchers</span>
                        <span className="font-mono font-semibold text-foreground">
                          {status.watcher_count}
                        </span>
                      </div>
                      {status.uptime_seconds !== null && (
                        <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                          <span className="text-muted-foreground">Uptime</span>
                          <span className="font-mono font-semibold text-foreground">
                            {formatUptime(status.uptime_seconds)}
                          </span>
                        </div>
                      )}
                      <div className="flex items-center justify-between py-1.5 border-b border-border/50">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          Errors
                        </span>
                        <Badge variant={status.error_count > 0 ? "warn" : "neutral"}>
                          {status.error_count}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between py-1.5">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          Last tick
                        </span>
                        <span className="text-muted-foreground text-[11px]">
                          {timeAgo(status.last_tick)}
                        </span>
                      </div>
                    </div>

                    {/* Manual tick button */}
                    <button
                      onClick={handleManualTick}
                      disabled={tickLoading || !status.enabled}
                      className="w-full flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs font-medium text-foreground hover:bg-muted/60 hover:border-accent/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {tickLoading ? (
                        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Zap className="h-3.5 w-3.5 text-accent" />
                      )}
                      {tickLoading ? "Triggering…" : "Manual Tick"}
                    </button>

                    {tickResult && (
                      <p
                        className={`text-[11px] text-center ${
                          tickResult.startsWith("Failed")
                            ? "text-bear"
                            : "text-bull"
                        }`}
                      >
                        {tickResult}
                      </p>
                    )}

                    {/* Dream link */}
                    <a
                      href={`/kairos?dream=${yesterday}`}
                      className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-accent transition-colors"
                    >
                      <ChevronRight className="h-3 w-3" />
                      View yesterday&apos;s dream summary
                    </a>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Watcher Cards */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
                Watchers
              </p>

              {watchersLoading && watchers.length === 0 && (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-16 rounded-xl border border-border bg-card animate-pulse"
                    />
                  ))}
                </div>
              )}

              {watchersError && (
                <div className="rounded-xl border border-bear/20 bg-bear/5 p-3 text-center">
                  <p className="text-xs text-bear">Failed to load watchers</p>
                </div>
              )}

              {!watchersLoading && !watchersError && watchers.length === 0 && (
                <div className="rounded-xl border border-border bg-muted/20 p-4 text-center">
                  <p className="text-xs text-muted-foreground">No watchers registered</p>
                </div>
              )}

              {watchers.map((w) => (
                <WatcherCard key={w.name} watcher={w} />
              ))}
            </div>
          </div>
        </div>

        {/* Dream Summary Section */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <p className="text-sm font-bold text-foreground">Dream Summaries</p>
            <span className="text-xs text-muted-foreground">— LLM-synthesized observation digests</span>
          </div>

          <DreamAccordion
            label="Yesterday's Dream"
            dream={yesterdayDream}
            defaultOpen
          />
          <DreamAccordion
            label="Today So Far"
            dream={todayDream}
            defaultOpen={false}
          />
        </div>

        <p className="text-xs text-muted-foreground text-center pb-2">
          Observations auto-refresh every 15s. Status and watchers auto-refresh every 30s.
        </p>
      </main>
    </div>
  );
}

```

### `dashboard/components/KairosStatusWidget.tsx`
```tsx
"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { Radio } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KairosStatus {
  enabled: boolean;
  running: boolean;
  tick_count: number;
  watcher_count: number;
  last_tick: string | null;
  uptime_seconds: number | null;
  error_count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch {
    return "unknown";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function KairosStatusWidget() {
  const router = useRouter();

  const { data, error } = useSWR<KairosStatus>("/kairos/status", fetcher, {
    refreshInterval: 30_000,
  });

  if (error || !data) {
    // Loading / error — show compact skeleton
    return (
      <Card
        className="cursor-pointer hover:border-accent/40 transition-colors"
        onClick={() => router.push("/kairos")}
      >
        <CardContent className="p-3">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-muted animate-pulse" />
            <span className="text-xs font-semibold text-muted-foreground tracking-wide">
              KAIROS
            </span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const isRunning = data.running === true;
  const isEnabled = data.enabled !== false;

  return (
    <Card
      className="cursor-pointer hover:border-accent/40 transition-colors"
      onClick={() => router.push("/kairos")}
    >
      <CardContent className="p-3 space-y-2">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {/* Pulsing indicator */}
            <span className="relative flex h-2 w-2">
              {isRunning && isEnabled ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-bull" />
                </>
              ) : (
                <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground" />
              )}
            </span>
            <span className="text-xs font-semibold text-foreground tracking-wide">
              KAIROS
            </span>
          </div>
          <Badge variant={isRunning && isEnabled ? "bull" : isEnabled ? "warn" : "neutral"}>
            {!isEnabled ? "Disabled" : isRunning ? "Running" : "Stopped"}
          </Badge>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-1">
            <Radio className="h-3 w-3" />
            <span>{data.tick_count ?? 0} ticks today</span>
          </div>
          <span className="text-border">·</span>
          <span>{data.watcher_count ?? 0} watchers</span>
          <span className="text-border">·</span>
          <span>{timeAgo(data.last_tick)}</span>
        </div>
      </CardContent>
    </Card>
  );
}

```

### `dashboard/components/KairosObservationFeed.tsx`
```tsx
"use client";

import { useState } from "react";
import useSWR from "swr";
import { AlertTriangle, Info, XCircle, Inbox } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Observation {
  timestamp: string;
  watcher: string;
  severity: "info" | "warning" | "critical";
  message: string;
  symbol?: string;
  notify: boolean;
}

interface ObservationsResponse {
  observations: Observation[];
  total: number;
}

type SeverityFilter = "all" | "warning+" | "critical";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function timeAgo(isoString: string): string {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch {
    return "";
  }
}

function severityBadgeVariant(severity: Observation["severity"]): "info" | "warn" | "bear" {
  switch (severity) {
    case "info":
      return "info";
    case "warning":
      return "warn";
    case "critical":
      return "bear";
  }
}

function SeverityIcon({ severity }: { severity: Observation["severity"] }) {
  switch (severity) {
    case "info":
      return <Info className="h-3.5 w-3.5" />;
    case "warning":
      return <AlertTriangle className="h-3.5 w-3.5" />;
    case "critical":
      return <XCircle className="h-3.5 w-3.5" />;
  }
}

function passesFilter(obs: Observation, filter: SeverityFilter): boolean {
  if (filter === "all") return true;
  if (filter === "warning+") return obs.severity === "warning" || obs.severity === "critical";
  if (filter === "critical") return obs.severity === "critical";
  return true;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface KairosObservationFeedProps {
  /** Minutes of history to show. Defaults to 60. */
  minutes?: number;
}

export function KairosObservationFeed({ minutes = 60 }: KairosObservationFeedProps) {
  const [filter, setFilter] = useState<SeverityFilter>("all");

  const { data, error, isLoading } = useSWR<ObservationsResponse>(
    `/kairos/observations?minutes=${minutes}`,
    fetcher,
    { refreshInterval: 15_000 }
  );

  const allObservations = data?.observations ?? [];
  const filtered = allObservations.filter((o) => passesFilter(o, filter)).slice(0, 50);

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>Observation Feed</CardTitle>
        <div className="flex items-center gap-1.5">
          {(["all", "warning+", "critical"] as SeverityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium border transition-colors ${
                filter === f
                  ? f === "critical"
                    ? "bg-bear/15 text-bear border-bear/20"
                    : f === "warning+"
                    ? "bg-warn/15 text-warn border-warn/20"
                    : "bg-accent/15 text-accent border-accent/20"
                  : "bg-muted text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              {f === "all" ? "All" : f === "warning+" ? "Warning+" : "Critical"}
            </button>
          ))}
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-hidden p-0">
        {/* Loading skeleton */}
        {isLoading && allObservations.length === 0 && (
          <div className="px-4 py-3 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-10 rounded-lg bg-muted animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center px-4">
            <XCircle className="h-6 w-6 text-bear" />
            <p className="text-sm font-medium text-bear">Failed to load observations</p>
            <p className="text-xs text-muted-foreground">Check that KAIROS is running</p>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center px-4">
            <Inbox className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {allObservations.length === 0
                ? `No observations in last ${minutes} minutes`
                : "No observations match the current filter"}
            </p>
          </div>
        )}

        {/* Feed rows */}
        {filtered.length > 0 && (
          <div className="overflow-y-auto max-h-[480px] divide-y divide-border/50">
            {filtered.map((obs, idx) => (
              <div
                key={`${obs.timestamp}-${obs.watcher}-${idx}`}
                className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/20 transition-colors"
              >
                {/* Severity icon */}
                <span
                  className={`mt-0.5 shrink-0 ${
                    obs.severity === "critical"
                      ? "text-bear"
                      : obs.severity === "warning"
                      ? "text-warn"
                      : "text-info"
                  }`}
                >
                  <SeverityIcon severity={obs.severity} />
                </span>

                {/* Main content */}
                <div className="flex-1 min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-foreground">
                      {obs.watcher}
                    </span>
                    {obs.symbol && (
                      <span className="font-mono text-xs text-muted-foreground">
                        {obs.symbol}
                      </span>
                    )}
                    <Badge variant={severityBadgeVariant(obs.severity)}>
                      <span className="flex items-center gap-1">
                        <SeverityIcon severity={obs.severity} />
                        {obs.severity}
                      </span>
                    </Badge>
                    {obs.notify && (
                      <Badge variant="info">notified</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {obs.message}
                  </p>
                </div>

                {/* Timestamp */}
                <span className="shrink-0 text-[11px] text-muted-foreground whitespace-nowrap mt-0.5">
                  {timeAgo(obs.timestamp)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="px-4 py-2 border-t border-border/50">
          <p className="text-[11px] text-muted-foreground">
            Showing last {minutes}min · {filtered.length} of {allObservations.length} observations · auto-refreshes every 15s
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

```

### `dashboard/components/TiltIndicatorWidget.tsx`
```tsx
"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TiltStatus {
  is_tilted: boolean;
  tilt_score: number;
  severity: "none" | "caution" | "warning" | "critical";
  tilt_indicators: string[];
  position_size_multiplier: number;
  cooldown_until: string | null;
  recent_trade_count: number;
  consecutive_losses: number;
  rapid_trades_30min: number;
  recent_vetoes: number;
  // Disabled/not-initialized state
  enabled?: boolean;
  message?: string;
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const SEVERITY_DOT: Record<string, string> = {
  none: "bg-green-500",
  caution: "bg-yellow-400",
  warning: "bg-orange-400",
  critical: "bg-red-500",
};

const SEVERITY_TEXT: Record<string, string> = {
  none: "text-green-400",
  caution: "text-yellow-400",
  warning: "text-orange-400",
  critical: "text-red-400",
};

const SEVERITY_BORDER: Record<string, string> = {
  none: "",
  caution: "border-yellow-400/30",
  warning: "border-orange-400/40",
  critical: "border-red-500/50 bg-red-500/5",
};

const SEVERITY_LABEL: Record<string, string> = {
  none: "CALM",
  caution: "CAUTION",
  warning: "WARNING",
  critical: "CRITICAL",
};

const BADGE_VARIANT: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  none: "bull",
  caution: "warn",
  warning: "warn",
  critical: "bear",
};

function formatIndicator(raw: string): string {
  return raw
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function useCooldownCountdown(cooldownUntil: string | null): string | null {
  // We do a simple static computation — no setInterval needed for the
  // dashboard's 10-second refresh cadence.
  if (!cooldownUntil) return null;
  const until = new Date(cooldownUntil).getTime();
  const now = Date.now();
  const remainMs = until - now;
  if (remainMs <= 0) return null;
  const mins = Math.floor(remainMs / 60000);
  const secs = Math.floor((remainMs % 60000) / 1000);
  return `${mins}m ${secs}s`;
}

// ── Main Component ────────────────────────────────────────────────────────────

export function TiltIndicatorWidget() {
  const { data, error, isLoading } = useSWR<TiltStatus>(
    "/safety/tilt",
    fetcher,
    { refreshInterval: 10_000, revalidateOnFocus: true }
  );

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <Card className="p-4 space-y-3 animate-pulse">
        <div className="h-3 w-32 bg-muted rounded" />
        <div className="h-6 w-24 bg-muted rounded" />
        <div className="h-2 w-full bg-muted rounded-full" />
        <div className="flex gap-2">
          <div className="h-5 w-20 bg-muted rounded" />
          <div className="h-5 w-24 bg-muted rounded" />
        </div>
      </Card>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <Card className="p-4 border-muted/50">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
          TILT MONITOR
        </p>
        <p className="text-sm text-muted-foreground">
          Engine offline or unavailable
        </p>
      </Card>
    );
  }

  // ── Disabled / not initialized ────────────────────────────────────────────
  if (data.enabled === false) {
    return (
      <Card className="p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
          TILT MONITOR
        </p>
        <p className="text-sm text-muted-foreground">
          {data.message ?? "Disabled"}
        </p>
      </Card>
    );
  }

  const severity = data.severity ?? "none";
  const score = data.tilt_score ?? 0;
  const scorePct = Math.round(score * 100);
  const multiplierPct = Math.round((data.position_size_multiplier ?? 1) * 100);
  const cooldown = useCooldownCountdown(data.cooldown_until);
  const dotColor = SEVERITY_DOT[severity] ?? SEVERITY_DOT.none;
  const textColor = SEVERITY_TEXT[severity] ?? SEVERITY_TEXT.none;
  const borderClass = SEVERITY_BORDER[severity] ?? "";
  const badgeVariant = BADGE_VARIANT[severity] ?? "neutral";

  // Bar color for the tilt score bar
  const barColor =
    severity === "critical"
      ? "bg-red-500"
      : severity === "warning"
      ? "bg-orange-400"
      : severity === "caution"
      ? "bg-yellow-400"
      : "bg-green-500";

  return (
    <Card className={`p-4 space-y-3 ${borderClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          TILT MONITOR
        </p>
        <div className="flex items-center gap-2">
          {/* Severity dot */}
          <span
            className={`w-2.5 h-2.5 rounded-full ${dotColor} ${
              severity !== "none" ? "animate-pulse" : ""
            }`}
          />
          <Badge variant={badgeVariant}>
            {SEVERITY_LABEL[severity] ?? severity.toUpperCase()}
          </Badge>
        </div>
      </div>

      {/* Tilt score bar */}
      <div className="space-y-1">
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-muted-foreground">Tilt Score</span>
          <span className={`text-sm font-mono font-semibold ${textColor}`}>
            {scorePct}%
          </span>
        </div>
        <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${scorePct}%` }}
          />
        </div>
      </div>

      {/* Position size multiplier */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">Position Size</span>
        <span
          className={`text-sm font-mono font-semibold ${
            multiplierPct < 100
              ? multiplierPct === 0
                ? "text-red-400"
                : "text-yellow-400"
              : "text-green-400"
          }`}
        >
          {multiplierPct === 0 ? "HALTED" : `${multiplierPct}%`}
        </span>
      </div>

      {/* Active indicators */}
      {data.tilt_indicators && data.tilt_indicators.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Active Indicators
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.tilt_indicators.map((ind) => (
              <span
                key={ind}
                className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50"
              >
                {formatIndicator(ind)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Cooldown countdown */}
      {cooldown && (
        <div className="flex items-center gap-2 border-t border-border/40 pt-2">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <p className="text-xs text-red-400 font-medium">
            Cooldown: {cooldown} remaining
          </p>
        </div>
      )}

      {/* Stats footer */}
      <div className="grid grid-cols-3 gap-x-3 border-t border-border/40 pt-2">
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Losses</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.consecutive_losses ?? 0) >= 3 ? "text-yellow-400" : ""
          }`}>
            {data.consecutive_losses ?? 0}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Trades/30m</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.rapid_trades_30min ?? 0) >= 5 ? "text-orange-400" : ""
          }`}>
            {data.rapid_trades_30min ?? 0}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Vetoes</p>
          <p className={`text-sm font-mono font-semibold ${
            (data.recent_vetoes ?? 0) >= 2 ? "text-yellow-400" : ""
          }`}>
            {data.recent_vetoes ?? 0}
          </p>
        </div>
      </div>
    </Card>
  );
}

```
