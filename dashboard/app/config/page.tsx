"use client";

import { useState, useEffect } from "react";
import { fetchEngine } from "@/lib/api";
import { FeatureFlagsReadOnlyPanel } from "@/components/FeatureFlagsReadOnlyPanel";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
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
  const configured = health.configured ?? {};
  const allConfigured = Object.values(configured).every(Boolean);
  const configuredCount = Object.values(configured).filter(Boolean).length;
  const totalCount = Object.values(configured).length;

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
        {Object.entries(configured).map(([key, ok]) => (
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
        <div className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] flex items-center justify-between px-6 py-3">
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
      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
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

        {/* Feature flags registry -- read-only (Plan Phase 8 row 6, D9: no toggle) */}
        <WidgetErrorBoundary name="Feature Flags Registry">
          <FeatureFlagsReadOnlyPanel />
        </WidgetErrorBoundary>

        {/* Category cards */}
        {data && (
          <div className="space-y-3">
            {Object.entries(data.categories ?? {}).map(([category, items]) => (
              <CategoryCard key={category} category={category} items={items} />
            ))}
            {Object.keys(data.categories ?? {}).length === 0 && (
              <div className="rounded-xl border border-border p-6 text-center text-sm text-muted-foreground">
                No configuration categories returned by the engine.
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
