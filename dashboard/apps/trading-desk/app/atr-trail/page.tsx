"use client";

import { useState } from "react";
import useSWR from "swr";
import { Badge } from "../../components/ui/badge";
import { AtrTrailChart } from "../../components/charts/AtrTrailChart";
import {
  LightweightSeriesChart,
  type SeriesPoint,
} from "../../components/charts/LightweightSeriesChart";
import { fetchAtrTrailTrades } from "../../lib/api";

const SYMBOLS = ["MES", "MGC", "MNQ", "MCL"];
const TIMEFRAMES = ["5m", "15m", "30m", "1h"];

export default function AtrTrailPage() {
  const [symbol, setSymbol] = useState("MES");
  const [timeframe, setTimeframe] = useState("5m");
  const [period, setPeriod] = useState(5);
  const [factor, setFactor] = useState(3.5);

  const { data, error, isLoading } = useSWR(
    ["atr-trail", symbol, timeframe, period, factor],
    () => fetchAtrTrailTrades({ symbol, timeframe, period, factor }),
    { revalidateOnFocus: false },
  );

  const equity: SeriesPoint[] =
    data?.equity.map((e) => ({ time: e.t as SeriesPoint["time"], value: e.v })) ?? [];
  const worst = data ? [...data.trades].sort((a, b) => a.pnl_usd - b.pnl_usd).slice(0, 12) : [];

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-lg font-semibold">ATR-Trail Strategy — Trade Visualizer</h1>
          <p className="text-xs text-slate-400">
            TOS ATRTrailingStopLE/SE flip on cached bars. Dotted line = the trail; arrows = entries
            (green win / red loss). The equity curve below is the whole strategy, not a sample.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded bg-slate-800 px-2 py-1"
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="rounded bg-slate-800 px-2 py-1"
          >
            {TIMEFRAMES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1">
            period
            <input
              type="number"
              value={period}
              min={2}
              max={30}
              onChange={(e) => setPeriod(Number(e.target.value))}
              className="w-14 rounded bg-slate-800 px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            factor
            <input
              type="number"
              value={factor}
              step={0.5}
              min={1}
              max={6}
              onChange={(e) => setFactor(Number(e.target.value))}
              className="w-16 rounded bg-slate-800 px-2 py-1"
            />
          </label>
        </div>
      </div>

      {isLoading && <div className="text-sm text-slate-400">Loading bars + computing trades…</div>}
      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
          Could not load ATR-trail data. Is the engine running and are {symbol} {timeframe} bars
          cached? ({String(error)})
        </div>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral">{data.n_trades} trades</Badge>
            <Badge variant={data.net_usd >= 0 ? "bull" : "bear"}>
              net ${data.net_usd.toLocaleString()}
            </Badge>
            <Badge variant="info">win rate {(data.win_rate * 100).toFixed(0)}%</Badge>
            <Badge variant="neutral">{data.bars.toLocaleString()} bars</Badge>
            {data.source_file && (
              <span className="text-xs text-slate-500">{data.source_file}</span>
            )}
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-2">
            <AtrTrailChart price={data.price} trail={data.trail} trades={data.trades} />
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-2">
            <div className="px-2 pb-1 text-xs text-slate-400">
              Equity curve — full period, all {data.n_trades} trades (net of commission + slippage)
            </div>
            <LightweightSeriesChart
              data={equity}
              type="line"
              color={data.net_usd >= 0 ? "#16c784" : "#ea3943"}
              height={200}
              interactive
            />
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
            <div className="pb-2 text-xs text-slate-400">Worst 12 trades — where it bled</div>
            <table className="w-full text-xs">
              <thead className="text-slate-500">
                <tr className="text-left">
                  <th className="py-1">entry</th>
                  <th>dir</th>
                  <th>entry px</th>
                  <th>exit px</th>
                  <th className="text-right">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {worst.map((t, i) => (
                  <tr key={i} className="border-t border-slate-800/60">
                    <td className="py-1">{new Date(t.entry_t * 1000).toISOString().slice(0, 16)}</td>
                    <td>{t.dir === 1 ? "LONG" : "SHORT"}</td>
                    <td>{t.entry_px.toFixed(2)}</td>
                    <td>{t.exit_px.toFixed(2)}</td>
                    <td className="text-right text-red-400">${t.pnl_usd.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
