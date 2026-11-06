"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import type { HealthResponse, PortfolioSnapshot } from "@/lib/api";
import { bookDisagreements, type BookLine } from "@/lib/bookDisagreement";
import type { HermesGatesReport } from "@/lib/hermesGates";
import { fetcher, localFetcher, UnreachableNote } from "./shared";

interface LossTrackerStatus {
  is_halted?: boolean;
  halt_until?: string | null;
}

interface PaperRow {
  symbol?: string;
  action?: string;
  side?: string;
  direction?: string;
  quantity?: number;
  status?: string;
}

interface PaperBook {
  positions?: PaperRow[];
  count?: number;
}

interface HealthView extends HealthResponse {
  ibgateway_port?: number | null;
}

function signedPaperQty(row: PaperRow): number {
  const qty = Number(row.quantity ?? 0);
  if (!Number.isFinite(qty)) return 0;
  const side = (row.action || row.side || row.direction || "").toUpperCase();
  if (side === "SELL" || side === "SHORT") return -Math.abs(qty);
  return qty;
}

function sideLabel(row: PaperRow): string {
  return row.action || row.side || row.direction || "—";
}

export function LockoutBlock({
  lockout,
  error,
}: {
  lockout: LossTrackerStatus | undefined;
  error?: unknown;
}) {
  let text = "…";
  let variant: "neutral" | "bear" | "bull" | "warn" = "neutral";
  if (error) {
    text = "unreachable";
    variant = "bear";
  } else if (lockout) {
    text = lockout.is_halted ? "halted" : "not halted";
    variant = lockout.is_halted ? "bear" : "bull";
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wider text-muted-foreground">Lockout</span>
      <Badge variant={variant}>{text}</Badge>
      {lockout?.halt_until ? (
        <span className="font-mono text-[11px] text-muted-foreground">until {lockout.halt_until}</span>
      ) : null}
    </div>
  );
}

export function GatesBlock({
  gates,
  error,
}: {
  gates: HermesGatesReport | undefined;
  error?: unknown;
}) {
  if (error) return <UnreachableNote endpoint="/api/operator/gates" />;
  if (!gates) return <p className="text-sm text-muted-foreground">…</p>;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">Hermes gates</span>
        <span className="text-sm text-foreground">
          {gates.found ? (gates.gates.length > 0 ? "hermes gates" : "gates file found, no gate lines") : "gates file missing"}
        </span>
      </div>
      {gates.gates.length > 0 ? (
        <ul className="space-y-1">
          {gates.gates.map((gate) => (
            <li key={`${gate.name}-${gate.status}`} className="flex items-center gap-2">
              <Badge
                variant={
                  gate.status === "pass" ? "bull" : gate.status === "fail" ? "bear" : gate.status === "warn" ? "warn" : "neutral"
                }
              >
                {gate.status}
              </Badge>
              <span className="text-sm text-foreground">{gate.name}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function OperatorScoreboard() {
  const { data: health, error: healthError } = useSWR<HealthView>("/health", fetcher, {
    refreshInterval: 15_000,
  });
  const { data: paper, error: paperError } = useSWR<PaperBook>("/portfolio/paper/positions", fetcher, {
    refreshInterval: 15_000,
  });
  const { data: portfolio, error: portfolioError } = useSWR<PortfolioSnapshot>("/portfolio", fetcher, {
    refreshInterval: 15_000,
  });
  const { data: lockout, error: lockoutError } = useSWR<LossTrackerStatus>(
    "/safety/loss-tracker/status",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: gates, error: gatesError } = useSWR<HermesGatesReport>("/api/operator/gates", localFetcher, {
    refreshInterval: 15_000,
  });

  const paperRows = paper?.positions ?? [];
  const paperLines: BookLine[] = paperRows.map((row) => ({
    symbol: row.symbol ?? "",
    quantity: signedPaperQty(row),
  }));
  const portfolioLines: BookLine[] = (portfolio?.positions ?? []).map((row) => ({
    symbol: row.symbol,
    quantity: row.quantity,
  }));
  const booksReady = Boolean(paper) && Boolean(portfolio) && !paperError && !portfolioError;
  const disagreements = booksReady ? bookDisagreements(portfolioLines, paperLines) : [];

  return (
    <section className="space-y-4 rounded-xl border-2 border-border bg-card p-5">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Operator scoreboard
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Engine book and Hermes gates. Read only.
        </p>
      </div>

      {healthError ? (
        <UnreachableNote endpoint="/health" />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={health ? (health.status === "ok" ? "bull" : "warn") : "neutral"}>
            {health ? health.status : "…"}
          </Badge>
          <Badge variant={health ? (health.paper_mode ? "info" : "warn") : "neutral"}>
            {health ? (health.paper_mode ? "paper" : "paper off") : "…"}
          </Badge>
          <Badge variant={health ? (health.live_trading ? "bear" : "info") : "neutral"}>
            {health ? (health.live_trading ? "live" : "live off") : "…"}
          </Badge>
          <Badge variant={health ? (health.kill_switch_active ? "bear" : "bull") : "neutral"}>
            {health ? (health.kill_switch_active ? "kill switch on" : "kill switch off") : "…"}
          </Badge>
          <Badge variant={health ? (health.ibkr_connected ? "bull" : "bear") : "neutral"}>
            {health
              ? `IB ${health.ibkr_connected ? "up" : "down"}${health.ibgateway_port ? ` ${health.ibgateway_port}` : ""}`
              : "…"}
          </Badge>
        </div>
      )}

      <LockoutBlock lockout={lockout} error={lockoutError} />

      <div className="space-y-2">
        <h3 className="text-xs uppercase tracking-wider text-muted-foreground">Open book</h3>
        {paperError ? (
          <UnreachableNote endpoint="/portfolio/paper/positions" />
        ) : !paper ? (
          <p className="text-sm text-muted-foreground">…</p>
        ) : paperRows.length === 0 ? (
          <p className="text-sm text-foreground">no open position</p>
        ) : (
          <ul className="space-y-1">
            {paperRows.map((row, index) => (
              <li key={`${row.symbol ?? "row"}-${index}`} className="font-mono text-xs text-foreground">
                {row.symbol ?? "—"} {sideLabel(row)} {row.quantity ?? "—"} {row.status ?? "open"}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-xs uppercase tracking-wider text-muted-foreground">Book check</h3>
        {paperError || portfolioError ? (
          <Badge variant="bear">book unreachable</Badge>
        ) : !booksReady ? (
          <p className="text-sm text-muted-foreground">…</p>
        ) : disagreements.length === 0 ? (
          <Badge variant="bull">matches</Badge>
        ) : (
          <ul className="space-y-1">
            {disagreements.map((message) => (
              <li key={message}>
                <Badge variant="warn">{message}</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>

      <GatesBlock gates={gates} error={gatesError} />
    </section>
  );
}
