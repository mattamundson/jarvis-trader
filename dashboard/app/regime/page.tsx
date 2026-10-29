"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Bell,
  ChevronDown,
  Search,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { RegimeScoreHistoryChart } from "@/components/regime/RegimeScoreHistoryChart";
import { VixPercentileRegimeCard } from "@/components/VixPercentileRegimeCard";
import {
  buildSampleRegime,
  fetchIntradayRegime,
  REGIME_SCALE_MAX,
  type IndicatorReading,
  type IntradayRegime,
  type RegimeDirection,
  type TimeframeScore,
} from "@/lib/regime";

const SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA"];
const REFRESH_MS = 30_000;

// ── Tone → tailwind helpers ──────────────────────────────────────────────────

function directionTextClass(d: RegimeDirection): string {
  if (d === "BULLISH") return "text-bull";
  if (d === "BEARISH") return "text-bear";
  return "text-warn";
}

function toneTextClass(tone: IndicatorReading["tone"]): string {
  if (tone === "bull") return "text-bull";
  if (tone === "bear") return "text-bear";
  return "text-warn";
}

function toneBarClass(tone: IndicatorReading["tone"]): string {
  if (tone === "bull") return "bg-bull";
  if (tone === "bear") return "bg-bear";
  return "bg-warn";
}

function arrowGlyph(arrow?: "up" | "down"): string {
  if (arrow === "up") return "▲ ";
  if (arrow === "down") return "▼ ";
  return "";
}

function formatGex(value: number): string {
  const sign = value >= 0 ? "+" : "-";
  const millions = Math.abs(value) / 1_000_000;
  return `${sign}$${millions.toFixed(1)}M`;
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function IntradayRegimePage() {
  const [symbol, setSymbol] = useState("SPY");
  const [showEma, setShowEma] = useState(true);

  // Live engine data; show error/empty state when unavailable instead of
  // falling back to a misleading deterministic sample.
  const { data: live, error, isLoading, mutate: refetchRegime } = useSWR<IntradayRegime>(
    ["regime", symbol],
    () => fetchIntradayRegime(symbol),
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );
  
  const engineDown = error || (!isLoading && !live);

  return (
    <div className="min-h-screen bg-background">
      <RegimeBanner />

      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5 lg:px-6">
        <TabsRow isLoading={isLoading && !live} engineDown={engineDown} />

        {/* Symbol + price + analyze */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-2xl font-extrabold tracking-tight text-info">
            {symbol}
          </span>
          {live && (
            <span className="font-mono text-2xl font-bold text-foreground">
              ${live.price.toFixed(2)}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <div className="relative">
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="appearance-none rounded-lg border border-border bg-card px-4 py-2 pr-9 font-mono text-sm font-semibold text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {SYMBOLS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
            <button
              onClick={() => refetchRegime()}
              disabled={isLoading}
              className="rounded-lg bg-gradient-to-r from-violet-500 to-indigo-500 px-5 py-2 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {isLoading ? "Analyzing…" : "Analyze"}
            </button>
          </div>
        </div>

        {engineDown ? (
          <div className="rounded-xl border border-warn/40 bg-warn/5 p-8 text-center">
            <p className="text-lg font-semibold text-warn mb-2">Engine Unavailable</p>
            <p className="text-sm text-muted-foreground">
              Cannot fetch regime data. Check engine connection at localhost:8010.
            </p>
          </div>
        ) : live ? (
          <>
            <VerdictCard data={live} />
            <RegimeScoreBar score={live.score} />
            <VixPercentileRegimeCard />
            <ScoreHistoryCard data={live} showEma={showEma} onToggleEma={() => setShowEma((v) => !v)} />
            <TimeframeScores scores={live.timeframeScores} />
            <IndicatorBreakdown timeframe={live.indicatorTimeframe} indicators={live.indicators} />
            <OptionsFlow flow={live.optionsFlow} />
          </>
        ) : (
          <div className="rounded-xl border border-border bg-card p-8 text-center">
            <p className="text-lg font-semibold text-muted-foreground mb-2">Loading…</p>
          </div>
        )}
      </main>
    </div>
  );
}

// ── Banner ───────────────────────────────────────────────────────────────────

function RegimeBanner() {
  return (
    <header className="bg-gradient-to-r from-teal-400 via-emerald-400 to-teal-500">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 lg:px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-900/80 font-mono text-[10px] font-bold leading-3 text-teal-300">
          EZ
        </div>
        <h1 className="text-lg font-extrabold tracking-tight text-white drop-shadow-sm sm:text-xl">
          Intraday Market Regime
        </h1>
        <div className="ml-auto hidden items-center gap-2 rounded-full bg-white/20 px-4 py-1.5 text-white backdrop-blur md:flex">
          <Search className="h-4 w-4 text-white/80" />
          <span className="text-sm text-white/80">Search here...</span>
        </div>
        <button
          aria-label="Notifications"
          className="flex h-9 w-9 items-center justify-center rounded-full text-white/90 hover:bg-white/15"
        >
          <Bell className="h-4 w-4" />
        </button>
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/90 font-mono text-[10px] font-bold text-teal-600">
          MM
        </div>
      </div>
    </header>
  );
}

// ── Tabs row ─────────────────────────────────────────────────────────────────

function TabsRow({
  isLoading,
  engineDown,
}: {
  isLoading: boolean;
  engineDown: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button className="rounded-lg border border-border bg-card px-4 py-2 text-xs font-semibold text-foreground">
        Intraday Regime Leaderboard (High Liquidity)
      </button>
      <button className="rounded-lg bg-violet-500/20 px-4 py-2 text-xs font-semibold text-violet-300">
        Ticker Intraday Market Regime
      </button>
      <span className="ml-auto">
        {engineDown ? (
          <Badge variant="bear" className="gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-bear" />
            Engine Down
          </Badge>
        ) : (
          <Badge variant="bull" className="gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${isLoading ? "animate-pulse" : ""} bg-bull`} />
            {isLoading ? "Loading…" : "Live Engine Data"}
          </Badge>
        )}
      </span>
    </div>
  );
}

// ── Verdict card ─────────────────────────────────────────────────────────────

function VerdictCard({ data }: { data: IntradayRegime }) {
  const bearish = data.direction === "BEARISH";
  const bullish = data.direction === "BULLISH";
  const gradient = bearish
    ? "from-rose-950/60 via-rose-900/30 to-slate-900/40 border-rose-500/30"
    : bullish
      ? "from-emerald-950/60 via-emerald-900/30 to-slate-900/40 border-emerald-500/30"
      : "from-amber-950/50 via-amber-900/20 to-slate-900/40 border-amber-500/30";

  return (
    <div
      className={`relative overflow-hidden rounded-xl border bg-gradient-to-r p-5 sm:p-6 ${gradient}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className={`text-3xl font-extrabold tracking-tight ${directionTextClass(data.direction)}`}>
            {data.direction}
          </h2>
          <p className="mt-1 text-sm text-foreground/80">
            {data.directionPct.toFixed(1)}% {data.direction.charAt(0) + data.direction.slice(1).toLowerCase()}
          </p>
          <p className="mt-2 flex items-center gap-1 text-sm text-foreground/70">
            {bearish ? (
              <TrendingDown className="h-4 w-4" />
            ) : (
              <TrendingUp className="h-4 w-4" />
            )}
            {data.guidance}
          </p>
          <span className="mt-3 inline-flex">
            <Badge variant={data.conviction === "HIGH" ? "bull" : "warn"}>
              {data.conviction}
            </Badge>
          </span>
        </div>
        <p
          className={`font-mono text-5xl font-extrabold tabular-nums sm:text-6xl ${directionTextClass(data.direction)}`}
        >
          {data.score > 0 ? "+" : ""}
          {data.score.toFixed(2)}
        </p>
      </div>
    </div>
  );
}

// ── Regime score bar ─────────────────────────────────────────────────────────

function RegimeScoreBar({ score }: { score: number }) {
  // Map -100..+100 onto 0..100% for the marker position.
  const pct = ((score + REGIME_SCALE_MAX) / (REGIME_SCALE_MAX * 2)) * 100;
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Regime Score
        </p>
        <p className="font-mono text-sm font-bold text-bear">
          {score > 0 ? "+" : ""}
          {score.toFixed(2)} <span className="text-muted-foreground">(±{REGIME_SCALE_MAX})</span>
        </p>
      </div>
      <div className="relative mt-3 h-2.5 rounded-full bg-gradient-to-r from-bear via-warn to-bull">
        <div
          className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow"
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
        <span>Bearish (-{REGIME_SCALE_MAX})</span>
        <span>Neutral (0)</span>
        <span>Bullish (+{REGIME_SCALE_MAX})</span>
      </div>
    </div>
  );
}

// ── Score history card ───────────────────────────────────────────────────────

const CHART_LEGEND: Array<{ label: string; color: string }> = [
  { label: "Bullish", color: "#22c55e" },
  { label: "Neutral", color: "#f59e0b" },
  { label: "Bearish", color: "#ef4444" },
  { label: "Short EMA", color: "#2dd4bf" },
  { label: "Long EMA", color: "#3b82f6" },
  { label: "Extra EMA", color: "#a855f7" },
];

function ScoreHistoryCard({
  data,
  showEma,
  onToggleEma,
}: {
  data: IntradayRegime;
  showEma: boolean;
  onToggleEma: () => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Today&apos;s Regime Score History
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={onToggleEma}
            className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-semibold transition-colors ${
              showEma
                ? "border-warn/40 bg-warn/15 text-warn"
                : "border-border bg-muted text-muted-foreground"
            }`}
          >
            EMA: {showEma ? "ON" : "OFF"}
          </button>
          <span className="font-mono text-[10px] text-muted-foreground">
            {data.snapshotCount} snapshots
          </span>
          <span className="font-mono text-[10px] font-semibold text-muted-foreground">
            SCORE / TIME (LOCAL)
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        {CHART_LEGEND.map((item) => (
          <span
            key={item.label}
            className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground"
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </span>
        ))}
      </div>

      <div className="mt-2">
        <RegimeScoreHistoryChart data={data.history} showEma={showEma} />
      </div>
    </div>
  );
}

// ── Timeframe scores ─────────────────────────────────────────────────────────

function TimeframeScores({ scores }: { scores: TimeframeScore[] }) {
  return (
    <div className="space-y-2">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Timeframe Scores
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {scores.map((tf) => {
          const bear = tf.bias === "BEAR";
          const bull = tf.bias === "BULL";
          const color = bear ? "text-bear" : bull ? "text-bull" : "text-warn";
          return (
            <div
              key={tf.label}
              className="rounded-xl border border-border bg-card p-4 text-center"
            >
              <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                {tf.label}
              </p>
              <p className={`mt-2 font-mono text-3xl font-extrabold tabular-nums ${color}`}>
                {tf.score > 0 ? "+" : ""}
                {tf.score.toFixed(2)}
              </p>
              <p className={`mt-1 flex items-center justify-center gap-1 text-xs font-semibold ${color}`}>
                {bear ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                {tf.bias}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Indicator breakdown ──────────────────────────────────────────────────────

function IndicatorBreakdown({
  timeframe,
  indicators,
}: {
  timeframe: string;
  indicators: IndicatorReading[];
}) {
  return (
    <div className="space-y-2">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Indicator Breakdown — {timeframe}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {indicators.map((ind) => (
          <div
            key={ind.label}
            className="flex flex-col rounded-xl border border-border bg-card p-3"
          >
            <p className="font-mono text-[9px] font-bold uppercase tracking-wider text-muted-foreground/70">
              {ind.label}
            </p>
            <p className={`mt-1.5 text-sm font-bold ${toneTextClass(ind.tone)}`}>
              {arrowGlyph(ind.arrow)}
              {ind.value}
            </p>
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{ind.detail}</p>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
              <div
                className={`h-full rounded-full ${toneBarClass(ind.tone)}`}
                style={{ width: `${Math.round(ind.fill * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Options flow ─────────────────────────────────────────────────────────────

function OptionsFlow({
  flow,
}: {
  flow: IntradayRegime["optionsFlow"];
}) {
  if (!flow) {
    return (
      <div className="space-y-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Options Flow
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {["Flow Signal", "Net GEX", "GEX Flip Level"].map((label) => (
            <div key={label} className="rounded-xl border border-dashed border-border bg-card p-4">
              <p className="font-mono text-[9px] font-bold uppercase tracking-wider text-muted-foreground/70">
                {label}
              </p>
              <p className="mt-1.5 text-sm text-muted-foreground/60">Not wired</p>
            </div>
          ))}
        </div>
      </div>
    );
  }
  const cards: Array<{ label: string; value: string; tone: string }> = [
    {
      label: "Flow Signal",
      value: flow.flowSignal.charAt(0) + flow.flowSignal.slice(1).toLowerCase(),
      tone: directionTextClass(flow.flowSignal),
    },
    {
      label: "Net GEX",
      value: formatGex(flow.netGex),
      tone: flow.netGex >= 0 ? "text-bull" : "text-bear",
    },
    {
      label: "GEX Flip Level",
      value: `$${flow.gexFlipLevel}`,
      tone: "text-foreground",
    },
  ];
  return (
    <div className="space-y-2">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Options Flow
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-border bg-card p-4">
            <p className="font-mono text-[9px] font-bold uppercase tracking-wider text-muted-foreground/70">
              {c.label}
            </p>
            <p className={`mt-1.5 text-xl font-bold ${c.tone}`}>{c.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
