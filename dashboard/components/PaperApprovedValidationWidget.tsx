"use client";

import useSWR from "swr";
import { ClipboardCheck, Loader2 } from "lucide-react";
import {
  fetchApprovedPaperGates,
  type ApprovedPaperGatesResponse,
  type ApprovedInstrumentGateRow,
} from "@/lib/api";

const fetcher = () => fetchApprovedPaperGates();

function gateLabel(name: string): string {
  const map: Record<string, string> = {
    profit_factor: "Profit factor",
    sharpe_ratio: "Sharpe",
    win_rate: "Win rate",
    total_trades: "Trades",
    days_active: "Days (distinct)",
    max_drawdown: "Max DD",
  };
  return map[name] ?? name;
}

function formatCurrent(g: ApprovedInstrumentGateRow["gates"][0]): string {
  if (g.name === "win_rate" || g.name === "max_drawdown") {
    return `${g.current}${g.unit || "%"}`;
  }
  if (g.name === "days_active" || g.name === "total_trades") {
    return String(Math.round(g.current));
  }
  return String(g.current);
}

function panelBorderClass(overallPass: boolean): string {
  return overallPass ? "border-[#00ff8833]" : "border-[#88888844]";
}

function statusBadgeClass(empty: boolean, overallPass: boolean): string {
  if (empty) return "text-[#888] bg-[#222]";
  return overallPass ? "text-[#00ff88] bg-[#00ff8818]" : "text-[#ffaa00] bg-[#ffaa0018]";
}

function SymbolColumn({ row }: { row: ApprovedInstrumentGateRow }) {
  const empty = row.trade_count === 0;
  return (
    <div
      className={`rounded-lg border p-3 space-y-2 bg-[#0a0a0c] ${panelBorderClass(row.overall_pass)}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm font-bold text-[#e0e0e0]">
          {row.symbol}
        </span>
        <span
          className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${statusBadgeClass(empty, row.overall_pass)}`}
        >
          {empty ? "no data" : row.overall_pass ? "all gates" : "in progress"}
        </span>
      </div>
      <p className="text-[10px] font-mono text-[#666]">
        {empty
          ? "No closed paper trades in SQLite for this symbol yet."
          : `${row.trade_count} closed · ${row.days_with_trades} distinct days`}
      </p>
      {!empty && (
        <ul className="space-y-1.5 pt-1">
          {row.gates.map((g) => (
            <li
              key={`${row.symbol}-${g.name}`}
              className="flex items-center justify-between text-[11px] font-mono"
            >
              <span className="text-[#888]">{gateLabel(g.name)}</span>
              <span className="flex items-center gap-2 tabular-nums">
                <span className={g.passes ? "text-[#6ee7b7]" : "text-[#f87171]"}>
                  {g.passes ? "✓" : "✗"}
                </span>
                <span className="text-[#ccc]">
                  {formatCurrent(g)}
                  <span className="text-[#555]"> / {g.target}</span>
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PaperApprovedValidationWidget() {
  const { data, error, isLoading } = useSWR<ApprovedPaperGatesResponse>(
    "approved-paper-gates",
    fetcher,
    { refreshInterval: 60_000, revalidateOnFocus: true }
  );

  return (
    <section className="rounded-xl border p-4 space-y-3 border-[#333] bg-[#08080a]">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="h-4 w-4 text-[#60a5fa]" />
        <h2 className="text-sm font-semibold tracking-tight text-[#e5e5e5]">
          Paper validation — MCL &amp; MNQ
        </h2>
        {isLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-[#666]" />}
      </div>
      <p className="text-[10px] leading-relaxed text-[#666]">
        Tier-1 approved futures vs project gates (PF ≥ 2, Sharpe ≥ 1.5, WR ≥ 55%, trades ≥ 60,
        distinct days ≥ 30, max DD ≤ 15%). Source: engine{" "}
        <code className="text-[9px]">/paper/validation/approved-paper-gates</code>.
      </p>

      {error && (
        <p className="text-xs font-mono text-[#f87171]">
          {error instanceof Error ? error.message : "Failed to load validation gates"}
        </p>
      )}

      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {data.instruments.map((row) => (
            <SymbolColumn key={row.symbol} row={row} />
          ))}
        </div>
      )}

      {data?.note && (
        <p className="text-[9px] font-mono leading-snug pt-1 text-[#555]">
          {data.note}
        </p>
      )}
    </section>
  );
}
