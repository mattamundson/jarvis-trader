"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 15_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface IBReport {
  id?: number;
  timestamp: string;
  symbol: string;
  ib_high: number | null;
  ib_low: number | null;
  ibu50: number | null;
  ibu100: number | null;
  ibd50: number | null;
  ibd100: number | null;
  context: string | null;
  plan: string | null;
  raw_text?: string;
}

interface IBReportsResponse {
  data: IBReport[];
  total: number;
  limit: number;
  offset: number;
}

function buildUrl(symbol: string, offset: number): string {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  params.set("limit", "20");
  params.set("offset", String(offset));
  return `/discord/ib-reports?${params.toString()}`;
}

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function PriceRow({ label, value, color }: { label: string; value: number | null; color?: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums font-semibold" style={{ color: color ?? "inherit" }}>
        {value != null ? value.toFixed(2) : "—"}
      </span>
    </div>
  );
}

export function IBReportCard() {
  const [symbol, setSymbol] = useState("");
  const [offset, setOffset] = useState(0);

  const url = buildUrl(symbol, offset);
  const { data, isLoading } = useSWR<IBReportsResponse>(url, fetcher, {
    refreshInterval: REFRESH_MS,
    keepPreviousData: true,
  });

  const rows = data?.data ?? [];
  const total = data?.total ?? 0;
  const pageSize = 20;

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-accent/50"
          placeholder="Symbol (ES, NQ…)"
          value={symbol}
          onChange={(e) => { setSymbol(e.target.value); setOffset(0); }}
        />
        <span className="font-mono text-[10px] text-muted-foreground ml-auto">
          {isLoading ? "Loading…" : `${total.toLocaleString()} reports`}
        </span>
      </div>

      {/* Cards grid */}
      {!rows.length ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center font-mono text-[10px] text-muted-foreground/50 italic">
          {isLoading ? "Loading IB reports…" : "No IB reports found"}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {rows.map((report, i) => (
            <div
              key={report.id ?? i}
              className="rounded-xl border border-border bg-card p-4 space-y-3"
            >
              {/* Header */}
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-bold" style={{ color: "#00d4ff" }}>
                  {report.symbol}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {fmt(report.timestamp)}
                </span>
              </div>

              {/* IB Range */}
              <div className="rounded-lg bg-muted/30 p-3 space-y-1.5 font-mono text-xs">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  IB Range
                </p>
                <PriceRow label="IB High" value={report.ib_high} color="#00ff88" />
                <PriceRow label="IB Low" value={report.ib_low} color="#ff4444" />
              </div>

              {/* Extension levels */}
              <div className="rounded-lg bg-muted/30 p-3 space-y-1.5 font-mono text-xs">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Extensions
                </p>
                <PriceRow label="IBU 50%" value={report.ibu50} color="#00ff8899" />
                <PriceRow label="IBU 100%" value={report.ibu100} color="#00ff88" />
                <PriceRow label="IBD 50%" value={report.ibd50} color="#ff444499" />
                <PriceRow label="IBD 100%" value={report.ibd100} color="#ff4444" />
              </div>

              {/* Context */}
              {report.context && (
                <div>
                  <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                    Context
                  </p>
                  <p className="font-mono text-[11px] text-foreground/80 leading-relaxed">
                    {report.context}
                  </p>
                </div>
              )}

              {/* Plan */}
              {report.plan && (
                <div>
                  <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                    Plan
                  </p>
                  <p className="font-mono text-[11px] text-foreground/80 leading-relaxed border-l-2 border-accent/40 pl-2">
                    {report.plan}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > pageSize && (
        <div className="flex items-center gap-3 justify-end">
          <button
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
            disabled={offset === 0}
            className="rounded-lg border border-border px-3 py-1 font-mono text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Prev
          </button>
          <span className="font-mono text-[10px] text-muted-foreground">
            {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
          </span>
          <button
            onClick={() => setOffset(offset + pageSize)}
            disabled={offset + pageSize >= total}
            className="rounded-lg border border-border px-3 py-1 font-mono text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
