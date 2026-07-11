"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
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

/**
 * Per-strategy gate-v2 verdict table ("which candidates clear the gate now").
 * Folded from the former /strategy-ledger page (P2.3) — the page shell (sticky
 * header + nav) is dropped so this mounts inside the /readiness layout; all data,
 * sorting, and the per-symbol ProdGateScorecard are preserved verbatim.
 */
export function StrategyLedgerView() {
  const { data, error, isLoading } = useSWR<LedgerResponse>(
    "strategy-ledger",
    fetchStrategyLedger,
    { refreshInterval: 60000 }
  );
  const [sortKey, setSortKey] = useState<SortKey>("verdict");
  const [asc, setAsc] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");

  // Distinct symbols present in the ledger (for the gate-scorecard selector).
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

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => (
    <TableHead
      className={`font-mono text-xs cursor-pointer select-none ${right ? "text-right" : ""}`}
      onClick={() => toggleSort(k)}
    >
      {label}
      {sortKey === k ? (asc ? " ▲" : " ▼") : ""}
    </TableHead>
  );

  const passCount = data?.n_pass ?? 0;
  const failCount = data?.n_fail ?? 0;
  const totalCount = data?.total ?? 0;

  return (
    <div className="space-y-4">
      {/* Summary chips */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5">
          <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Thresholds</span>
          <span className="text-xs font-mono text-foreground">PF-CI ≥ 1.10</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs font-mono text-foreground">p_edge ≥ 0.95</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs font-mono text-foreground">MC-DD ≤ 5%</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs font-mono text-foreground">DSR ≥ 0.10</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="text-bull font-mono font-bold">{passCount} PASS</span>
          <span>/</span>
          <span className="text-bear font-mono font-bold">{failCount} FAIL</span>
          <span className="text-muted-foreground">of {totalCount}</span>
        </div>
        <span className="text-xs text-muted-foreground font-mono">
          {rows.length} strategies · refreshes every 60s
        </span>
        {isLoading && <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" />}
      </div>

      {/* Per-symbol gate scorecard (US-005) */}
      {symbols.length > 0 && (
        <div>
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

      {/* Error state */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          Error loading ledger: {String(error)}
        </div>
      )}

      {/* Table */}
      {rows.length === 0 && !isLoading ? (
        <div className="flex items-center justify-center h-40 rounded-xl border border-border bg-card">
          <p className="text-muted-foreground">No verdicts found</p>
        </div>
      ) : isLoading && rows.length === 0 ? (
        <div className="flex items-center justify-center h-40 rounded-xl border border-border bg-card">
          <p className="text-muted-foreground animate-pulse">Loading strategy verdicts…</p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-x-auto">
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
                  <TableCell className="font-mono text-sm text-right tabular-nums">{fmt(r.pf_ci_lower)}</TableCell>
                  <TableCell className="font-mono text-sm text-right tabular-nums">{fmt(r.p_edge)}</TableCell>
                  <TableCell className="font-mono text-sm text-right tabular-nums">{fmt(r.mc_95th_dd_pct)}</TableCell>
                  <TableCell className="font-mono text-sm text-right tabular-nums">{fmt(r.dsr)}</TableCell>
                  <TableCell>
                    <Badge variant={wfoVariant(r.wfo_consistency)}>{r.wfo_consistency ?? "—"}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm text-right tabular-nums">{fmt(r.fixed_params_min_pf)}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{r.cost_survives_through ?? "—"}</TableCell>
                  <TableCell className="font-mono text-sm text-right tabular-nums">{r.oos_trades ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
