"use client";

import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Options Chain Card — Mission Control.
 *
 * Mirrors the options surface on Matt's TOS /ES chart: the near-the-money
 * call/put strikes with last, bid, ask, and IV.  Data from:
 *   GET /options/chain/{symbol}
 *
 * Read-only — analysis surface only, never routes orders.
 */

type OptionRow = {
  strike?: number;
  right?: string; // "call" | "put"
  option_symbol?: string;
  last?: number | null;
  bid?: number | null;
  ask?: number | null;
  iv?: number | null;
  delta?: number | null;
};

type ChainResponse = {
  symbol?: string;
  underlying_price?: number | null;
  expiry?: string;
  calls?: OptionRow[];
  puts?: OptionRow[];
  // Alt shapes some engines use:
  chain?: OptionRow[];
  contracts?: OptionRow[];
};

const SYMBOLS = ["SPY", "QQQ"] as const;

function fmt(n: number | null | undefined, digits = 2): string {
  return n == null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

function fmtIV(n: number | null | undefined): string {
  // iv may arrive as decimal (0.22) or percentage (22)
  if (n == null || !Number.isFinite(n)) return "—";
  const pct = n > 1 ? n : n * 100;
  return `${pct.toFixed(1)}%`;
}

/** Coalesce the many possible chain shapes into one normalized row list. */
function normalize(chain: ChainResponse | null): {
  underlying: number | null;
  rows: OptionRow[];
} {
  if (!chain) return { underlying: null, rows: [] };
  const underlying = chain.underlying_price ?? null;
  const calls = chain.calls ?? [];
  const puts = chain.puts ?? [];
  const flat = chain.chain ?? chain.contracts ?? [];
  // Prefer the split calls/puts shape; fall back to a flat list.
  const rows = calls.length || puts.length ? [...calls, ...puts] : flat;
  return { underlying, rows };
}

export function OptionsChainCard() {
  const [symbol, setSymbol] = useState<string>(SYMBOLS[0]);
  const [underlying, setUnderlying] = useState<number | null>(null);
  const [rows, setRows] = useState<OptionRow[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const chain = await fetchEngine<ChainResponse>(`/options/chain/${symbol}`);
        if (cancelled) return;
        const { underlying, rows } = normalize(chain);
        setUnderlying(underlying);
        setRows(rows);
        setOffline(false);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "fetch failed";
        if (/(^|\D)(404|503)(\D|$)/.test(msg)) setOffline(true);
      }
    }
    load();
    const interval = setInterval(load, POLL_INTERVAL.SLOW);
    return () => { cancelled = true; clearInterval(interval); };
  }, [symbol]);

  if (offline) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-foreground">Options Chain</h3>
          <Badge variant="bear" className="ml-auto">OFFLINE</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Options chain unavailable — /options/chain/{symbol} returned no data
          (chains empty when the OPRA subscription or data gateway is down).
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Layers className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">Options Chain</h3>
        {/* Symbol selector */}
        <div className="ml-auto flex gap-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                symbol === s
                  ? "bg-accent/15 text-accent border-accent/30"
                  : "bg-background text-muted-foreground border-border"
              }`}
              onClick={() => setSymbol(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {underlying != null && (
        <div className="text-[10px] text-muted-foreground">
          Underlying: <span className="font-mono text-foreground">{fmt(underlying)}</span>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="text-left font-medium py-1">Type</th>
              <th className="text-right font-medium py-1">Strike</th>
              <th className="text-right font-medium py-1">Last</th>
              <th className="text-right font-medium py-1">Bid</th>
              <th className="text-right font-medium py-1">Ask</th>
              <th className="text-right font-medium py-1">IV</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-muted-foreground py-3">
                  Loading chain…
                </td>
              </tr>
            ) : (
              rows.slice(0, 16).map((r, i) => {
                const isCall = r.right === "call" || r.right === "C";
                return (
                  <tr key={i} className="border-b border-border/40">
                    <td className={`py-0.5 ${isCall ? "text-bull" : "text-bear"}`}>
                      {isCall ? "C" : "P"}
                    </td>
                    <td className="text-right text-foreground">{fmt(r.strike, 0)}</td>
                    <td className="text-right text-foreground">{fmt(r.last)}</td>
                    <td className="text-right text-muted-foreground">{fmt(r.bid)}</td>
                    <td className="text-right text-muted-foreground">{fmt(r.ask)}</td>
                    <td className="text-right text-muted-foreground">{fmtIV(r.iv)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="text-[10px] text-muted-foreground border-t border-border pt-2 font-mono">
        /options/chain/{symbol}
      </div>
    </div>
  );
}