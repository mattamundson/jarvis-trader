"use client";

import { useMemo } from "react";
import useSWR from "swr";
import type { SeriesMarker, Time } from "lightweight-charts";
import { CandlestickChart } from "@/components/command-center/charts/CandlestickChart";
import {
  useChartData,
  type ChartSymbol,
  type ChartTimeframe,
} from "@/hooks/useChartData";
import { useLiveLastPrice } from "@/hooks/useLiveLastPrice";
import { fetchEngine, type TradeRecord } from "@/lib/api";

const SYMBOLS: ChartSymbol[] = ["MES", "MGC", "MNQ", "MCL"];
const TIMEFRAMES: ChartTimeframe[] = ["5m", "15m", "1h", "4h", "1d"];

const UP = "#00ff88";
const DOWN = "#ff4466";

function toUnix(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

/**
 * Build entry/exit markers for closed trades on the selected symbol, clipped to
 * the loaded bar window so off-chart history doesn't clutter the axis.
 */
function buildMarkers(
  trades: TradeRecord[] | undefined,
  symbol: ChartSymbol,
  firstBarTime: number | null,
  lastBarTime: number | null,
): SeriesMarker<Time>[] {
  if (!trades?.length || firstBarTime == null || lastBarTime == null) return [];
  const out: SeriesMarker<Time>[] = [];

  for (const t of trades) {
    if (!t.symbol || !(t.symbol === symbol || t.symbol.startsWith(symbol))) continue;
    const isLong = t.side === "BUY";

    const entryT = toUnix(t.entry_time);
    if (entryT != null && entryT >= firstBarTime && entryT <= lastBarTime) {
      out.push({
        time: entryT as Time,
        position: isLong ? "belowBar" : "aboveBar",
        shape: isLong ? "arrowUp" : "arrowDown",
        color: isLong ? UP : DOWN,
        text: `${t.side} ${t.entry_price}`,
      });
    }

    const exitT = toUnix(t.exit_time);
    if (exitT != null && exitT >= firstBarTime && exitT <= lastBarTime) {
      const pnl = t.realized_pnl;
      out.push({
        time: exitT as Time,
        position: isLong ? "aboveBar" : "belowBar",
        shape: isLong ? "arrowDown" : "arrowUp",
        color: (pnl ?? 0) >= 0 ? UP : DOWN,
        text: pnl != null ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}` : "EXIT",
      });
    }
  }

  // lightweight-charts requires markers in ascending time order.
  out.sort((a, b) => (a.time as number) - (b.time as number));
  return out;
}

interface PriceChartPanelProps {
  symbol: ChartSymbol;
  timeframe: ChartTimeframe;
  onSymbolChange: (s: ChartSymbol) => void;
  onTimeframeChange: (tf: ChartTimeframe) => void;
  height?: number;
  /** Overlay closed-trade entry/exit markers (default true). */
  showTrades?: boolean;
}

export function PriceChartPanel({
  symbol,
  timeframe,
  onSymbolChange,
  onTimeframeChange,
  height = 460,
  showTrades = true,
}: PriceChartPanelProps) {
  const { bars, technical, barsError } = useChartData(symbol, timeframe);
  const livePrice = useLiveLastPrice(symbol);

  const { data: trades } = useSWR<TradeRecord[]>(
    showTrades ? ["/portfolio/history/trades", "CLOSED"] : null,
    (): Promise<TradeRecord[]> =>
      fetchEngine<unknown>("/portfolio/history/trades?status=CLOSED&limit=500")
        .then((raw) => {
          // Endpoint may return a bare array or a {trades|data:[...]} wrapper.
          if (Array.isArray(raw)) return raw as TradeRecord[];
          const w = raw as { trades?: TradeRecord[]; data?: TradeRecord[] };
          return w?.trades ?? w?.data ?? [];
        })
        .catch(() => [] as TradeRecord[]),
    { refreshInterval: 60_000, revalidateOnFocus: false },
  );

  const markers = useMemo(() => {
    if (!showTrades || !bars.length) return [];
    return buildMarkers(trades, symbol, bars[0].time, bars[bars.length - 1].time);
  }, [trades, symbol, bars, showTrades]);

  const pill = (active: boolean) =>
    `px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors ${
      active
        ? "bg-accent/20 text-accent"
        : "bg-background border border-border text-muted-foreground hover:text-foreground"
    }`;

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mr-1">
            Price Chart
          </p>
          {SYMBOLS.map((s) => (
            <button key={s} className={pill(s === symbol)} onClick={() => onSymbolChange(s)}>
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              className={pill(tf === timeframe)}
              onClick={() => onTimeframeChange(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {barsError ? (
        <div
          className="flex items-center justify-center text-sm text-red-400 font-mono"
          style={{ height }}
        >
          Failed to load bars for {symbol}
        </div>
      ) : bars.length ? (
        // Mount only once bars exist: CandlestickChart creates its chart in a
        // mount effect, so mounting it with empty bars leaves a dead container
        // that never re-inits when bars arrive (matches the command-center gate).
        <CandlestickChart
          bars={bars}
          technical={technical}
          markers={markers}
          livePrice={livePrice}
          height={height}
        />
      ) : (
        <div
          className="flex items-center justify-center text-sm text-muted-foreground font-mono"
          style={{ height }}
        >
          Loading {symbol} bars…
        </div>
      )}

      {showTrades && (
        <div className="mt-3 flex items-center gap-4 text-[11px] text-muted-foreground font-mono">
          <span className="flex items-center gap-1.5">
            <span style={{ color: UP }}>▲</span> long entry / profitable exit
          </span>
          <span className="flex items-center gap-1.5">
            <span style={{ color: DOWN }}>▼</span> short entry / losing exit
          </span>
          {markers.length > 0 && <span>· {markers.length} trade markers</span>}
        </div>
      )}
    </div>
  );
}
