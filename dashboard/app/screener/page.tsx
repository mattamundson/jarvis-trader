"use client";

import React, { useCallback, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Crosshair,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertCircle,
} from "lucide-react";
import { screenMovers } from "@/lib/api";
import type { ScreenResponse, ScreenedRow, ScreenerFilterInput } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

// Scan codes the engine's /ib-scanner/screen accepts as a universe source.
// FUT_* codes scan CME futures (GLOBEX) — the active instruments (MES, MGC) live here,
// not in the equity codes above them.
const SCAN_CODES = [
  "TOP_PERC_GAIN",
  "TOP_PERC_LOSE",
  "HOT_BY_VOLUME",
  "TOP_OPEN_PERC_GAIN",
  "HIGH_OPEN_GAP",
  "MOST_ACTIVE",
  "FUT_HOT_BY_VOLUME",
  "FUT_TOP_PERC_GAIN",
  "FUT_TOP_PERC_LOSE",
] as const;

// Threshold defaults mirror the GreenStar2 screener (and the engine defaults).
type FilterForm = {
  scanCode: string;
  symbols: string;
  maxSymbols: string;
  xFrom50Min: string;
  xFrom50Max: string;
  rvolMin: string;
  xFromLodMax: string;
  chgPctMin: string;
  mmMin: string;
};

const DEFAULT_FORM: FilterForm = {
  scanCode: "TOP_PERC_GAIN",
  symbols: "",
  maxSymbols: "25",
  xFrom50Min: "0",
  xFrom50Max: "4",
  rvolMin: "1",
  xFromLodMax: "70",
  chgPctMin: "0",
  mmMin: "",
};

// Splits a comma/space/newline-separated symbol list into an upper-cased array,
// or null when the field is blank (falls back to the Universe scan code).
function parseSymbols(raw: string): string[] | null {
  const syms = raw
    .split(/[\s,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  return syms.length > 0 ? syms : null;
}

function numOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function fmt(n: number | null, digits = 2): string {
  return n === null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

function mmVariant(score: number): "bull" | "info" | "neutral" {
  if (score >= 7) return "bull";
  if (score >= 5) return "info";
  return "neutral";
}

export default function ScreenerPage() {
  const [form, setForm] = useState<FilterForm>(DEFAULT_FORM);
  const [data, setData] = useState<ScreenResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRejected, setShowRejected] = useState(false);

  const update = useCallback(
    (key: keyof FilterForm) =>
      (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
        setForm((f) => ({ ...f, [key]: e.target.value })),
    []
  );

  const runScan = useCallback(async () => {
    setLoading(true);
    setError(null);
    const symbols = parseSymbols(form.symbols);
    const req: ScreenerFilterInput = {
      // Explicit symbols bypass the ENABLE_IB_SCANNER gate entirely (engine-side) and
      // take precedence over the Universe scan code when both are present.
      ...(symbols ? { symbols } : { scan_code: form.scanCode }),
      max_symbols: numOrNull(form.maxSymbols) ?? 25,
      x_from_50_min: numOrNull(form.xFrom50Min),
      x_from_50_max: numOrNull(form.xFrom50Max),
      rvol_min: numOrNull(form.rvolMin),
      x_from_lod_max: numOrNull(form.xFromLodMax),
      chg_pct_min: numOrNull(form.chgPctMin),
      mm_min: numOrNull(form.mmMin),
    };
    try {
      setData(await screenMovers(req));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [form]);

  return (
    <div className="min-h-screen bg-background">
      <header className="bg-gradient-to-r from-sky-500 via-indigo-500 to-violet-500">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 lg:px-6">
          <Link
            href="/"
            className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-900/80 text-white/90 hover:bg-slate-900"
            aria-label="Back to dashboard"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <Crosshair className="h-5 w-5 text-white" />
          <h1 className="text-lg font-extrabold tracking-tight text-white drop-shadow-sm sm:text-xl">
            Pine Screener
          </h1>
          <Badge variant="info" className="ml-1 bg-white/20 text-white">
            BETA
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-4 px-4 py-6 lg:px-6">
        <ExploratoryBanner what="Screener output is an unfiltered candidate list" />
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Filters</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field label="Universe">
                <select
                  value={form.scanCode}
                  onChange={update("scanCode")}
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                >
                  {SCAN_CODES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
              <NumField label="Max symbols" value={form.maxSymbols} onChange={update("maxSymbols")} />
              <NumField label="xFrom50 min" value={form.xFrom50Min} onChange={update("xFrom50Min")} />
              <NumField label="xFrom50 max" value={form.xFrom50Max} onChange={update("xFrom50Max")} />
              <NumField label="RVOL min" value={form.rvolMin} onChange={update("rvolMin")} />
              <NumField label="%fromLoD max" value={form.xFromLodMax} onChange={update("xFromLodMax")} />
              <NumField label="Chg% min" value={form.chgPctMin} onChange={update("chgPctMin")} />
              <NumField label="MM min (0–8)" value={form.mmMin} onChange={update("mmMin")} placeholder="off" />
            </div>
            <Field label="Symbols (optional — overrides Universe, no IB scanner required)">
              <textarea
                value={form.symbols}
                onChange={update("symbols")}
                placeholder="e.g. MES=F, MGC=F, GC=F (yfinance format — bare IB symbols like MES won't resolve)"
                rows={2}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm font-mono"
              />
            </Field>
            <button
              onClick={runScan}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
            >
              <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              {loading ? "Scanning…" : "Scan"}
            </button>
            <p className="text-xs text-muted-foreground">
              Pipes the read-only IB scanner movers (or the Symbols list above) through the
              GreenStar2-style filter chain. Leave a threshold field blank to disable that filter.
              Universe scan codes require the engine&apos;s IB scanner (ENABLE_IB_SCANNER=1) and a
              connected IB Gateway; the Symbols field bypasses both and fetches bars via yfinance
              instead — use FUT_* codes or yfinance futures tickers (MES=F, MGC=F) to screen the
              active instruments rather than equities.
            </p>
          </CardContent>
        </Card>

        {error && (
          <Card>
            <CardContent className="flex items-center gap-2 py-4 text-sm text-bear">
              <AlertCircle className="h-4 w-4" />
              {error}
            </CardContent>
          </Card>
        )}

        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Badge variant={data.enabled ? "bull" : "warn"}>
                scanner {data.enabled ? "enabled" : "disabled"}
              </Badge>
              <Badge variant="neutral">source: {data.universe_source}</Badge>
              <span>
                {data.passed_count} focus / {data.total_candidates} candidates
              </span>
            </div>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold">
                  Focus names ({data.focus.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                {data.focus.length === 0 ? (
                  <p className="py-4 text-sm text-muted-foreground">
                    No candidates passed every active filter.
                  </p>
                ) : (
                  <ScreenTable rows={data.focus} />
                )}
              </CardContent>
            </Card>

            {data.rejected.length > 0 && (
              <Card>
                <CardHeader>
                  <button
                    onClick={() => setShowRejected((s) => !s)}
                    className="flex w-full items-center justify-between text-sm font-semibold"
                  >
                    <span>Rejected ({data.rejected.length})</span>
                    <span className="text-xs text-muted-foreground">
                      {showRejected ? "hide" : "show"}
                    </span>
                  </button>
                </CardHeader>
                {showRejected && (
                  <CardContent>
                    <ScreenTable rows={data.rejected} showReasons />
                  </CardContent>
                )}
              </Card>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function NumField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
}) {
  return (
    <Field label={label}>
      <input
        type="text"
        inputMode="decimal"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
      />
    </Field>
  );
}

function ScreenTable({ rows, showReasons = false }: { rows: ScreenedRow[]; showReasons?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Last</TableHead>
            <TableHead className="text-right">%fromLoD</TableHead>
            <TableHead className="text-right">RVOL</TableHead>
            <TableHead className="text-right">xFrom50</TableHead>
            <TableHead className="text-right">Chg%</TableHead>
            <TableHead className="text-right">ChgOpen%</TableHead>
            <TableHead className="text-right">ATR%</TableHead>
            <TableHead className="text-center">MM</TableHead>
            {showReasons && <TableHead>Failed</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.symbol ?? Math.random()}>
              <TableCell className="font-mono font-semibold">{r.symbol ?? "—"}</TableCell>
              <TableCell className="text-right">{fmt(r.last_price)}</TableCell>
              <TableCell className="text-right">{fmt(r.x_from_lod_pct)}</TableCell>
              <TableCell className="text-right">{fmt(r.rvol)}</TableCell>
              <TableCell className="text-right">{fmt(r.x_from_50)}</TableCell>
              <TableCell className="text-right">
                <span className="inline-flex items-center justify-end gap-1">
                  {r.chg_pct !== null && r.chg_pct < 0 ? (
                    <TrendingDown className="h-3 w-3 text-bear" />
                  ) : (
                    <TrendingUp className="h-3 w-3 text-bull" />
                  )}
                  <span className={r.chg_pct !== null && r.chg_pct < 0 ? "text-bear" : "text-bull"}>
                    {fmt(r.chg_pct)}
                  </span>
                </span>
              </TableCell>
              <TableCell className="text-right">{fmt(r.chg_open_pct)}</TableCell>
              <TableCell className="text-right">{fmt(r.atr_pct)}</TableCell>
              <TableCell className="text-center">
                <Badge variant={mmVariant(r.mm_score)}>{r.mm_score}</Badge>
              </TableCell>
              {showReasons && (
                <TableCell className="text-xs text-muted-foreground">
                  {r.reasons.join("; ")}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
