"use client";

import useSWR from "swr";
import { Activity, Gauge, Hash, Layers, TrendingUp } from "lucide-react";
import { fetchEngine } from "@/lib/api";
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

// The generator runs every 30 min during RTH; 60s polling surfaces a fresh
// snapshot within a minute of the write.
const REFRESH_MS = 60_000;

interface LadderRow {
  multiple: number;
  label: string;
  level: number;
  p_above: number | null;
  p_touch?: number | null;
  p_fail?: number | null;
}

interface OpportunityCandidate {
  structure: string;
  thesis: string;
  net_price: number;
  max_loss: number;
  max_gain: number;
  breakeven: number;
  pop: number | null;
  ev: number | null;
  ev_to_max_loss: number | null;
  reward_to_risk: number;
  liquidity_score: number;
  score: number;
  reject_reasons: string[];
  journal_url?: string;
  journal_note?: string;
}

interface OpportunityBoard {
  symbol: string;
  expiry: string;
  spot: number;
  status: "ok" | "degraded" | string;
  source?: string;
  source_confidence?: number;
  source_notes?: string[];
  candidate_count?: number;
  rejected_count?: number;
  candidates: OpportunityCandidate[];
  rejected_candidates?: OpportunityCandidate[];
  reject_summary: string[];
  disclaimer: string;
}

interface Horizon {
  label: "nearest" | "end_of_week" | string;
  expiry: string;
  dte_calendar: number;
  atm_strike: number | null;
  atm_iv: number | null;
  straddle_mid: number | null;
  expected_move_abs: number | null;
  expected_move_pct: number | null;
  prob_ladder: LadderRow[];
  opportunity_board?: OpportunityBoard;
  quality: "ok" | "degraded" | string;
  notes: string[];
}

interface SymbolBlock {
  spot: number;
  quote_ts: number | null;
  horizons: Horizon[];
}

interface RegimeBlock {
  vix: number;
  vix3m: number;
  slope: number;
  regime: "CONTANGO" | "FLAT" | "BACKWARDATION" | string;
  vix_percentile_1y: number;
  as_of_date: string;
  source: string;
}

interface OptionsSignalsSnapshot {
  schema_version: number;
  generated_at: number;
  quote_ts: number | null;
  data_delayed_minutes: number;
  stale_after_s: number;
  data_quality: "ok" | "partial" | string;
  errors: string[];
  disclaimer: string;
  regime: RegimeBlock | null;
  symbols: Record<string, SymbolBlock | null>;
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function fmtEpochSeconds(epoch: number | null): string {
  if (epoch == null) return "—";
  try {
    return new Date(epoch * 1000).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function pct(value: number | null, digits = 0): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

const REGIME_VARIANT: Record<string, "info" | "neutral" | "warn"> = {
  CONTANGO: "info",
  FLAT: "neutral",
  BACKWARDATION: "warn",
};

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground/60">{icon}</span>
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
      </div>
      <p className="font-mono text-2xl font-bold tabular-nums leading-none text-foreground">
        {value}
      </p>
      {sub && <p className="font-mono text-[10px] text-muted-foreground truncate">{sub}</p>}
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2 animate-pulse">
      <div className="h-2.5 w-20 bg-muted rounded" />
      <div className="h-7 w-28 bg-muted rounded" />
      <div className="h-2.5 w-16 bg-muted rounded" />
    </div>
  );
}

function structureLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function money(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(digits)}`;
}

function OpportunityBoardMini({ board }: { board?: OpportunityBoard }) {
  if (!board) {
    return (
      <p className="font-mono text-[10px] text-muted-foreground italic">
        Opportunity board unavailable — regenerate options snapshot.
      </p>
    );
  }
  const top = board.candidates.slice(0, 3);
  return (
    <div className="rounded-lg border border-border/80 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Defined-risk opportunity board · ANALYSIS_ONLY
        </p>
        <div className="flex items-center gap-2">
          {board.source_confidence != null && (
            <Badge variant={board.source_confidence >= 0.7 ? "info" : "static"} className="font-mono text-[9px]">
              SRC {pct(board.source_confidence)}
            </Badge>
          )}
          <Badge variant={board.status === "ok" ? "info" : "static"} className="font-mono text-[9px]">
            {board.status.toUpperCase()}
          </Badge>
        </div>
      </div>
      {top.length === 0 ? (
        <p className="font-mono text-[10px] text-muted-foreground italic">
          No bounded-risk candidates passed this cycle. {board.reject_summary.join(" · ")}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="font-mono text-[10px]">STRUCTURE</TableHead>
              <TableHead className="font-mono text-[10px]">POP</TableHead>
              <TableHead className="font-mono text-[10px]">EV/MAX LOSS</TableHead>
              <TableHead className="font-mono text-[10px]">MAX LOSS</TableHead>
              <TableHead className="font-mono text-[10px]">BREAKEVEN</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {top.map((candidate) => (
              <TableRow key={`${candidate.structure}-${candidate.breakeven}`}>
                <TableCell className="font-mono text-[10px] uppercase">
                  <div>{structureLabel(candidate.structure)}</div>
                  {candidate.journal_url && (
                    <a href={candidate.journal_url} title={candidate.journal_note ?? "Open journal"} className="text-[9px] text-accent hover:underline">
                      journal handoff
                    </a>
                  )}
                </TableCell>
                <TableCell className="font-mono text-[10px] tabular-nums">
                  {candidate.pop != null ? pct(candidate.pop) : "—"}
                </TableCell>
                <TableCell className="font-mono text-[10px] tabular-nums">
                  {candidate.ev_to_max_loss != null ? pct(candidate.ev_to_max_loss, 1) : "—"}
                </TableCell>
                <TableCell className="font-mono text-[10px] tabular-nums">
                  {money(candidate.max_loss)}
                </TableCell>
                <TableCell className="font-mono text-[10px] tabular-nums">
                  {candidate.breakeven.toFixed(2)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {board.source_notes && board.source_notes.length > 0 && (
        <p className="font-mono text-[9px] text-muted-foreground/70">
          Source: {board.source ?? "unknown"} · {board.source_notes.slice(0, 2).join(" · ")}
        </p>
      )}
      {board.rejected_candidates && board.rejected_candidates.length > 0 && (
        <p className="font-mono text-[9px] text-muted-foreground/70">
          Rejected: {board.rejected_candidates.slice(0, 2).map((c) => `${structureLabel(c.structure)} (${c.reject_reasons.join(", ")})`).join(" · ")}
        </p>
      )}
    </div>
  );
}

function HorizonCard({ horizon }: { horizon: Horizon }) {
  const em = horizon.expected_move_abs;
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {horizon.label === "nearest" ? "Nearest expiry" : "End of week"}
        </p>
        {horizon.quality === "degraded" && (
          <Badge variant="static" className="font-mono text-[9px]">
            DEGRADED
          </Badge>
        )}
      </div>
      <p className="font-mono text-xl font-bold tabular-nums leading-none text-foreground">
        {em != null ? `±$${em.toFixed(2)}` : "—"}
        <span className="ml-2 text-sm font-normal text-muted-foreground">
          {em != null ? `±${pct(horizon.expected_move_pct, 2)}` : ""}
        </span>
      </p>
      <p className="font-mono text-[10px] text-muted-foreground">
        exp {horizon.expiry} ({horizon.dte_calendar}d) · ATM {horizon.atm_strike ?? "—"} · ATM IV{" "}
        {pct(horizon.atm_iv, 1)}
      </p>
      {horizon.prob_ladder.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="font-mono text-[10px]">LEVEL</TableHead>
              <TableHead className="font-mono text-[10px]">PRICE</TableHead>
              <TableHead className="font-mono text-[10px]">P(CLOSE ABOVE)</TableHead>
              <TableHead className="font-mono text-[10px]">P(CLOSE BELOW)</TableHead>
              <TableHead className="font-mono text-[10px]">P(TOUCH)</TableHead>
              <TableHead className="font-mono text-[10px]">P(FAIL)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {horizon.prob_ladder.map((row) => (
              <TableRow key={row.label}>
                <TableCell className="font-mono text-[11px] text-muted-foreground">
                  {row.label}
                </TableCell>
                <TableCell className="font-mono text-[11px] tabular-nums">
                  {row.level.toFixed(2)}
                </TableCell>
                <TableCell className="font-mono text-[11px] tabular-nums">
                  {row.p_above != null ? pct(row.p_above) : "—"}
                </TableCell>
                <TableCell className="font-mono text-[11px] tabular-nums">
                  {row.p_above != null ? pct(1 - row.p_above) : "—"}
                </TableCell>
                <TableCell className="font-mono text-[11px] tabular-nums">
                  {row.p_touch != null ? pct(row.p_touch) : "—"}
                </TableCell>
                <TableCell className="font-mono text-[11px] tabular-nums">
                  {row.p_fail != null ? pct(row.p_fail) : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {horizon.prob_ladder.some((row) => row.p_touch != null) && (
        <p className="font-mono text-[9px] text-muted-foreground/70">
          P(TOUCH)/P(FAIL) are reflection-implied from the same delta surface
          (≈2× OTM close-probability; zero-drift first-passage estimate, not
          calibrated).
        </p>
      )}
      <OpportunityBoardMini board={horizon.opportunity_board} />
      {horizon.notes.length > 0 && (
        <p className="font-mono text-[9px] text-muted-foreground/70">{horizon.notes.join(" · ")}</p>
      )}
    </div>
  );
}

function SymbolCard({ symbol, block }: { symbol: string; block: SymbolBlock | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-sm flex items-center justify-between">
          <span className="flex items-center gap-2">
            <TrendingUp className="h-3.5 w-3.5 text-accent" />
            {symbol}
            {block && (
              <span className="tabular-nums text-muted-foreground">
                ${block.spot.toFixed(2)}
              </span>
            )}
          </span>
          {block && (
            <span className="text-[10px] font-normal text-muted-foreground">
              quote {fmtEpochSeconds(block.quote_ts)} (15-min delayed)
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!block && (
          <p className="font-mono text-xs text-muted-foreground italic">
            {symbol} chain unavailable this cycle — see errors below.
          </p>
        )}
        {block && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {block.horizons.map((h) => (
              <HorizonCard key={h.label} horizon={h} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function OptionsSignalsPanel() {
  const { data, error, isLoading } = useSWR<OptionsSignalsSnapshot>(
    "/options-signals/latest",
    fetcher,
    { refreshInterval: REFRESH_MS },
  );

  const notGeneratedYet = (error as { status?: number } | undefined)?.status === 404;
  const fresh = data ? Date.now() / 1000 - data.generated_at < data.stale_after_s : false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-sm flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Hash className="h-3.5 w-3.5 text-accent" />
            SPY/QQQ Options — Market-Implied (no edge claimed)
          </span>
          {data && (
            <span className="flex items-center gap-2">
              {data.data_quality === "partial" && (
                <Badge variant="warn" className="font-mono text-[9px]">
                  PARTIAL
                </Badge>
              )}
              <Badge variant={fresh ? "live" : "static"} className="font-mono text-[9px]">
                {fresh ? "FRESH SNAPSHOT" : "STALE SNAPSHOT"} · {fmtEpochSeconds(data.generated_at)}
              </Badge>
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="font-mono text-[10px] text-muted-foreground">
          Market-implied decision support only. Uses delayed option-chain / VIX inputs when
          available; no edge, fillability, or executable quote is claimed.
        </p>
        {isLoading && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <LoadingCard />
            <LoadingCard />
            <LoadingCard />
            <LoadingCard />
          </div>
        )}
        {notGeneratedYet && (
          <p className="font-mono text-xs text-muted-foreground italic">
            No options snapshot yet — the generator hasn&apos;t produced one. It runs every 30
            minutes during market hours.
          </p>
        )}
        {error && !notGeneratedYet && (
          <p className="font-mono text-xs text-muted-foreground italic">
            Engine unreachable — options snapshot unavailable.
          </p>
        )}
        {data && (
          <>
            {data.regime ? (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <MetricCard
                  icon={<Gauge className="h-3.5 w-3.5" />}
                  label="VIX term structure"
                  value={
                    <Badge
                      variant={REGIME_VARIANT[data.regime.regime] ?? "neutral"}
                      className="font-mono text-xs"
                    >
                      {data.regime.regime}
                    </Badge>
                  }
                  sub={`as of ${data.regime.as_of_date} (daily closes)`}
                />
                <MetricCard
                  icon={<Activity className="h-3.5 w-3.5" />}
                  label="VIX"
                  value={data.regime.vix.toFixed(2)}
                  sub={`${(data.regime.vix_percentile_1y * 100).toFixed(0)}th percentile (1y)`}
                />
                <MetricCard
                  icon={<Activity className="h-3.5 w-3.5" />}
                  label="VIX3M"
                  value={data.regime.vix3m.toFixed(2)}
                  sub="3-month implied vol index"
                />
                <MetricCard
                  icon={<Layers className="h-3.5 w-3.5" />}
                  label="Slope (VIX3M − VIX)"
                  value={`${data.regime.slope >= 0 ? "+" : ""}${(data.regime.slope * 100).toFixed(2)}`}
                  sub="vol points · >+0.5 contango, <−0.5 backwardation"
                />
              </div>
            ) : (
              <p className="font-mono text-xs text-muted-foreground italic">
                VIX/VIX3M regime unavailable this cycle.
              </p>
            )}
            <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
              {Object.entries(data.symbols).map(([symbol, block]) => (
                <SymbolCard key={symbol} symbol={symbol} block={block} />
              ))}
            </div>
            {data.errors.length > 0 && (
              <p className="font-mono text-[10px] text-muted-foreground">
                Errors: {data.errors.join(" · ")}
              </p>
            )}
            <p className="font-mono text-[10px] text-muted-foreground">{data.disclaimer}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
