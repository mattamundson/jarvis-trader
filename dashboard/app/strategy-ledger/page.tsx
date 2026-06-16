"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { fetchStrategyLedger, type LedgerEntry, type LedgerResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ProdGateScorecard } from "@/components/ProdGateScorecard";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type SortKey = "symbol" | "verdict" | "pf_ci_lower" | "dsr" | "mc_95th_dd_pct" | "oos_trades";

function fmt(v: number | null | undefined, digits = 2): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function verdictVariant(v: string | null): "bull" | "bear" | "neutral" {
  if (v === "PASS") return "bull";
  if (v === "FAIL") return "bear";
  return "neutral";
}

function wfoVariant(v: string | null): "bull" | "warn" | "bear" | "neutral" {
  if (v === "STRONG") return "bull";
  if (v === "MODERATE") return "warn";
  if (v === "WEAK") return "bear";
  return "neutral";
}

export default function StrategyLedgerPage() {
  const { data, error, isLoading } = useSWR<LedgerResponse>(
    "strategy-ledger",
    fetchStrategyLedger,
    { refreshInterval: 60000 }
  );
  const [sortKey, setSortKey] = useState<SortKey>("verdict");
  const [asc, setAsc] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");

  // Distinct symbols present in the ledger, PASS-first order preserved enough
  // for a sensible default (the first sorted row's symbol).
  const symbols = useMemo(() => {
    const seen = new Set<string>();
    for (const e of data?.entries ?? []) {
      if (e.symbol) seen.add(e.symbol);
    }
    return Array.from(seen);
  }, [data]);

  const rows = useMemo(() => {
    const entries: LedgerEntry[] = data?.entries ? [...data.entries] : [];
    entries.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      // PASS before FAIL when sorting by verdict
      if (sortKey === "verdict") {
        const rank = (v: string | null) => (v === "PASS" ? 0 : v === "FAIL" ? 1 : 2);
        return (rank(a.verdict) - rank(b.verdict)) * (asc ? 1 : -1) * -1;
      }
      if (typeof av === "number" && typeof bv === "number") return asc ? av - bv : bv - av;
      return asc
        ? String(av ?? "").localeCompare(String(bv ?? ""))
        : String(bv ?? "").localeCompare(String(av ?? ""));
    });
    return entries;
  }, [data, sortKey, asc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc(!asc);
    else {
      setSortKey(key);
      setAsc(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-muted-foreground">Loading strategy ledger…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-2">
        <p className="text-destructive font-semibold">Error loading ledger</p>
        <p className="text-sm text-muted-foreground">{String(error)}</p>
      </div>
    );
  }

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => (
    <TableHead
      className={`font-mono text-xs cursor-pointer select-none ${right ? "text-right" : ""}`}
      onClick={() => toggleSort(k)}
    >
      {label}
      {sortKey === k ? (asc ? " ▲" : " ▼") : ""}
    </TableHead>
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <h1 className="font-mono text-lg font-bold text-foreground">Strategy Ledger</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Gate-v2 backtest verdicts • {data?.n_pass ?? 0} PASS / {data?.n_fail ?? 0} FAIL of{" "}
          {data?.total ?? 0} • thresholds: PF-CI ≥ 1.10, p_edge ≥ 0.95, MC-DD ≤ 5%, DSR ≥ 0.10
        </p>
      </div>

      {symbols.length > 0 && (
        <div className="flex-shrink-0 px-6 pt-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-xs text-muted-foreground">Gate scorecard:</span>
            <div className="flex flex-wrap gap-1">
              {symbols.map((sym) => {
                const active = (selectedSymbol || symbols[0]) === sym;
                return (
                  <button
                    key={sym}
                    onClick={() => setSelectedSymbol(sym)}
                    className={`font-mono text-xs px-2 py-0.5 rounded border transition-colors ${
                      active
                        ? "bg-primary/15 border-primary text-foreground"
                        : "border-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {sym}
                  </button>
                );
              })}
            </div>
          </div>
          <ProdGateScorecard symbol={selectedSymbol || symbols[0]} />
        </div>
      )}

      <div className="flex-1 overflow-auto px-6 py-4">
        {rows.length === 0 ? (
          <div className="flex items-center justify-center h-40">
            <p className="text-muted-foreground">No verdicts found</p>
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <Th k="symbol" label="Symbol" />
                  <TableHead className="font-mono text-xs">Family</TableHead>
                  <Th k="verdict" label="Verdict" />
                  <TableHead className="font-mono text-xs">Via</TableHead>
                  <Th k="pf_ci_lower" label="PF-CI" right />
                  <TableHead className="font-mono text-xs text-right">p_edge</TableHead>
                  <Th k="mc_95th_dd_pct" label="MC-DD %" right />
                  <Th k="dsr" label="DSR" right />
                  <TableHead className="font-mono text-xs">WFO</TableHead>
                  <TableHead className="font-mono text-xs text-right">min-PF</TableHead>
                  <TableHead className="font-mono text-xs">cost</TableHead>
                  <Th k="oos_trades" label="OOS" right />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r, i) => (
                  <TableRow key={`${r.symbol}-${r.family}-${r.rank}-${i}`} className="hover:bg-muted/30 transition-colors">
                    <TableCell className="font-mono font-semibold text-sm">{r.symbol ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {r.family ?? "—"}
                      {typeof r.rank === "number" ? ` #${r.rank}` : ""}
                    </TableCell>
                    <TableCell>
                      <Badge variant={verdictVariant(r.verdict)}>{r.verdict ?? "—"}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{r.passed_via ?? "—"}</TableCell>
                    <TableCell className="font-mono text-sm text-right">{fmt(r.pf_ci_lower)}</TableCell>
                    <TableCell className="font-mono text-sm text-right">{fmt(r.p_edge)}</TableCell>
                    <TableCell className="font-mono text-sm text-right">{fmt(r.mc_95th_dd_pct)}</TableCell>
                    <TableCell className="font-mono text-sm text-right">{fmt(r.dsr)}</TableCell>
                    <TableCell>
                      <Badge variant={wfoVariant(r.wfo_consistency)}>{r.wfo_consistency ?? "—"}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-sm text-right">{fmt(r.fixed_params_min_pf)}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{r.cost_survives_through ?? "—"}</TableCell>
                    <TableCell className="font-mono text-sm text-right">{r.oos_trades ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <div className="flex-shrink-0 px-6 py-3 border-t border-border text-xs text-muted-foreground">
        {rows.length} strategies • verdicts read from engine/data/gate_v2_verdicts • refreshes every 60s
      </div>
    </div>
  );
}
