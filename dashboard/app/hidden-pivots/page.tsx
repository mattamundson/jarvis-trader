"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Crosshair,
  TrendingUp,
  TrendingDown,
  Eye,
  Hand,
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { fetchHiddenPivotsScan, fetchPriceCoverage, fetchPriceSnapshot } from "@/lib/api";
import type { HPSignal, PriceSnapshot } from "@/lib/api";
import { filterToPriceCoveredSymbols } from "@/lib/hiddenPivotsPriceCoverage";

// ── Constants ────────────────────────────────────────────────────────────────

const TIMEFRAMES = ["1d", "1h", "4h", "15m", "5m"];
const REFRESH_MS = 60_000;
// Price snapshot has a 60s server cache; poll a bit faster so the UI catches a
// refresh within ~15s of it landing. Cheap — repeats just hit the cache.
const PRICE_REFRESH_MS = 15_000;
// Which watchlist symbols have a real price floor changes only when the CSV
// backtest cache is refreshed (occasional) — no need to poll this often.
const PRICE_COVERAGE_REFRESH_MS = 5 * 60_000;

const PATTERN_LABEL: Record<string, string> = {
  rounded_base: "Rounded base / saucer",
  rounded_top: "Rounded top",
  bull_flag: "Bull flag",
  bear_flag: "Bear flag",
  triangle: "Symmetrical triangle",
  channel_reversal: "Channel reversal",
};

// Bullish-leaning patterns watch ABOVE the trigger; bearish ones watch BELOW.
const BULLISH_PATTERNS = new Set(["rounded_base", "bull_flag", "channel_reversal"]);
const BEARISH_PATTERNS = new Set(["rounded_top", "bear_flag"]);

// ── Formatters ───────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function scanTimeLabel(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

// Sort: armed (LONG/SHORT) first, then WATCH, then SOH; within a group by confidence desc.
const BIAS_RANK: Record<string, number> = { LONG: 0, SHORT: 0, WATCH: 1, SOH: 2 };

// ── Bias + lean rendering ────────────────────────────────────────────────────

function BiasBadge({ bias }: { bias: HPSignal["bias"] }) {
  if (bias === "LONG") {
    return (
      <Badge variant="bull" className="gap-1 text-[10px] font-bold">
        <TrendingUp className="h-3 w-3" /> LONG
      </Badge>
    );
  }
  if (bias === "SHORT") {
    return (
      <Badge variant="bear" className="gap-1 text-[10px] font-bold">
        <TrendingDown className="h-3 w-3" /> SHORT
      </Badge>
    );
  }
  if (bias === "SOH") {
    return (
      <Badge variant="neutral" className="gap-1 text-[10px] font-bold">
        <Hand className="h-3 w-3" /> SOH
      </Badge>
    );
  }
  return (
    <Badge variant="warn" className="gap-1 text-[10px] font-bold">
      <Eye className="h-3 w-3" /> WATCH
    </Badge>
  );
}

/** Directional lean for a row — armed bias when present, else inferred from pattern. */
function rowLean(s: HPSignal): "bull" | "bear" | "none" {
  if (s.bias === "LONG") return "bull";
  if (s.bias === "SHORT") return "bear";
  if (s.pattern && BULLISH_PATTERNS.has(s.pattern)) return "bull";
  if (s.pattern && BEARISH_PATTERNS.has(s.pattern)) return "bear";
  return "none";
}

function TriggerCell({ s }: { s: HPSignal }) {
  if (s.trigger_price == null) return <span className="text-muted-foreground">{"—"}</span>;
  const lean = rowLean(s);
  const Icon = lean === "bull" ? ArrowUpRight : lean === "bear" ? ArrowDownRight : null;
  const color = lean === "bull" ? "text-bull" : lean === "bear" ? "text-bear" : "text-foreground";
  const word = lean === "bull" ? "above" : lean === "bear" ? "below" : "at";
  return (
    <span className={`inline-flex items-center gap-1 font-mono tabular-nums ${color}`}>
      {Icon && <Icon className="h-3 w-3" />}
      <span className="text-muted-foreground text-[10px]">{word}</span>
      {fmt(s.trigger_price)}
    </span>
  );
}

function CrossCell({ s }: { s: HPSignal }) {
  if (s.bars_since_cross < 0 || s.last_cross_dir === "none") {
    return <span className="text-muted-foreground font-mono text-xs">{"—"}</span>;
  }
  const color = s.last_cross_dir === "bull" ? "text-bull" : "text-bear";
  const fresh = s.bars_since_cross <= 2;
  return (
    <span className={`font-mono text-xs ${color}`}>
      {s.last_cross_dir} · {s.bars_since_cross}b{fresh ? " ●" : ""}
    </span>
  );
}

/** Live last price + daily change for a row. REST-polled (works remotely). */
function PriceCell({ snap }: { snap: PriceSnapshot[string] | undefined }) {
  const px = snap?.last_price;
  if (px == null) return <span className="text-muted-foreground font-mono text-xs">{"—"}</span>;
  const chg = snap?.change_pct;
  const chgColor = chg == null ? "text-muted-foreground" : chg > 0 ? "text-bull" : chg < 0 ? "text-bear" : "text-muted-foreground";
  const sign = chg != null && chg > 0 ? "+" : "";
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap font-mono tabular-nums">
      <span className="text-foreground">{fmt(px)}</span>
      {chg != null && (
        <span className={`text-[10px] ${chgColor}`}>
          {sign}
          {chg.toFixed(2)}%
        </span>
      )}
    </span>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function HiddenPivotsPage() {
  const [timeframe, setTimeframe] = useState("1d");

  const { data, error, isLoading, isValidating, mutate } = useSWR(
    ["hp-scan", timeframe],
    () => fetchHiddenPivotsScan(timeframe),
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  // Which symbols have a real live-price fallback floor (PRB-21) — a symbol
  // with no CSV-cache floor shows "--" with certainty once IBKR + Polygon's
  // rate limit both miss, so there's no point polling it every 15s. Scanning
  // (above) is unaffected and still covers the full watchlist.
  const { data: priceCoverage } = useSWR(
    "hp-price-coverage",
    fetchPriceCoverage,
    { refreshInterval: PRICE_COVERAGE_REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  // Live prices for the scanned symbols, polled independently of the (slow) scan.
  const symbolList = useMemo(() => {
    const scanned = (data?.details ?? []).map((d) => d.symbol);
    return filterToPriceCoveredSymbols(scanned, priceCoverage?.covered_symbols);
  }, [data, priceCoverage]);
  const { data: prices } = useSWR<PriceSnapshot>(
    symbolList.length ? ["hp-prices", symbolList.join(",")] : null,
    () => fetchPriceSnapshot(symbolList),
    { refreshInterval: PRICE_REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const rows = useMemo(() => {
    const details = data?.details ?? [];
    return [...details].sort((a, b) => {
      const ra = BIAS_RANK[a.bias] ?? 1;
      const rb = BIAS_RANK[b.bias] ?? 1;
      if (ra !== rb) return ra - rb;
      return b.confidence - a.confidence;
    });
  }, [data]);

  const armed = data?.signals?.length ?? 0;
  const watch = data?.watch_symbols?.length ?? 0;
  const soh = data?.soh_symbols?.length ?? 0;
  const scanned = data?.symbols_scanned ?? 0;
  const broadWatch = scanned > 0 && (watch + soh) / scanned >= 0.7;

  return (
    <div className="space-y-5 p-4 md:p-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight text-foreground">
            <Crosshair className="h-5 w-5 text-accent" />
            Hidden Pivots
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Rick Ackerman HiddenPivots scanner — pattern, EMA fan, 2-line oscillator, and the
            HP level ladder. Analysis-only; never routes orders. No oscillator circle = no entry.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="flex overflow-hidden rounded-md border border-border">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 font-mono transition-colors ${
                  tf === timeframe
                    ? "bg-accent/15 text-accent font-bold"
                    : "text-muted-foreground hover:bg-muted/40"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => mutate()}
            disabled={isValidating}
            className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 font-semibold text-foreground hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isValidating ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stat chips */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-md border border-border bg-card px-2.5 py-1 font-mono text-muted-foreground">
          {scanned} scanned
        </span>
        <span className="rounded-md border border-bull/30 bg-bull/10 px-2.5 py-1 font-mono text-bull">
          {armed} armed
        </span>
        <span className="rounded-md border border-warn/30 bg-warn/10 px-2.5 py-1 font-mono text-warn">
          {watch} watch
        </span>
        <span className="rounded-md border border-border bg-muted/40 px-2.5 py-1 font-mono text-muted-foreground">
          {soh} SOH
        </span>
        <span className="ml-auto font-mono text-muted-foreground/70">
          scan {scanTimeLabel(data?.scan_time)} · auto 60s
        </span>
      </div>

      {/* Market-condition banner */}
      {broadWatch && (
        <div className="rounded-lg border border-warn/30 bg-warn/10 px-4 py-2.5 text-xs text-warn">
          <span className="font-bold">Broad WATCH</span> — {watch + soh}/{scanned} names are
          un-armed (no oscillator crossover circle). Patterns and levels are mapped; entries are not
          triggered. Sit on hands until a circle prints.
        </div>
      )}

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-left">
                  {[
                    "Symbol",
                    "Price",
                    "Bias",
                    "Pattern",
                    "Trigger",
                    "Stop (tight/risk)",
                    "Targets",
                    "Last cross",
                    "r/s",
                    "Conf",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {isLoading && (
                  <tr>
                    <td colSpan={10} className="px-3 py-10 text-center text-xs text-muted-foreground">
                      <RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />
                      Scanning {timeframe}…
                    </td>
                  </tr>
                )}

                {error && !isLoading && (
                  <tr>
                    <td colSpan={10} className="px-3 py-10 text-center text-xs text-bear">
                      Scan failed: {error instanceof Error ? error.message : "engine unreachable"}
                    </td>
                  </tr>
                )}

                {!isLoading && !error && rows.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-3 py-10 text-center text-xs text-muted-foreground">
                      No results for {timeframe}.
                    </td>
                  </tr>
                )}

                {rows.map((s) => {
                  const armedRow = s.bias === "LONG" || s.bias === "SHORT";
                  return (
                    <tr
                      key={s.symbol}
                      className={`transition-colors ${
                        armedRow ? "bg-accent/5 hover:bg-accent/10" : "hover:bg-muted/30"
                      }`}
                    >
                      <td className="px-3 py-2.5">
                        <span className="font-mono text-sm font-bold text-foreground">{s.symbol}</span>
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        <PriceCell snap={prices?.[s.symbol]} />
                      </td>
                      <td className="px-3 py-2.5">
                        <BiasBadge bias={s.bias} />
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                        {s.pattern ? PATTERN_LABEL[s.pattern] ?? s.pattern : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                        <TriggerCell s={s} />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                        {s.tight_stop != null ? (
                          <>
                            <span className="text-bear">{fmt(s.tight_stop)}</span>
                            <span className="text-muted-foreground/50"> / {fmt(s.riskier_stop)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs tabular-nums whitespace-nowrap">
                        {s.targets.length ? (
                          <span className="text-bull">
                            {s.targets.slice(0, 3).map((t) => fmt(t)).join(" · ")}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">{"—"}</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        <CrossCell s={s} />
                      </td>
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                        <span
                          className={
                            s.rs_rw_score > 0.05
                              ? "text-bull"
                              : s.rs_rw_score < -0.05
                                ? "text-bear"
                                : "text-muted-foreground"
                          }
                        >
                          {s.rs_rw_label}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-foreground">
                        {(s.confidence * 100).toFixed(0)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <p className="pb-4 text-center text-[11px] text-muted-foreground">
        HiddenPivots is display/analysis only — it never constructs an order or touches the safety
        layer. A green ● marks a crossover that printed within the last 2 bars. Price is a live
        last/quote (≈60s cache) polled every 15s; levels update on the 60s scan. Universe is tunable
        via the engine&apos;s <span className="font-mono">SCAN_SYMBOLS</span> setting.
      </p>
    </div>
  );
}
