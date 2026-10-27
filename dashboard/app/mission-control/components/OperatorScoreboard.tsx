"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { bookDisagreements } from "@/lib/bookDisagreement";
import type { HermesGatesReport } from "@/lib/hermesGates";
import { fetcher, localFetcher, UnreachableNote } from "./shared";

interface ScoreboardHealth {
  status?: string;
  live_trading?: boolean;
  paper_mode?: boolean;
  kill_switch_active?: boolean;
  ibgateway_port?: number | null;
  ibkr_connected?: boolean;
}

interface LossTrackerStatus {
  is_halted?: boolean;
  halt_until?: string | null;
}

interface BookPosition {
  symbol?: string;
  quantity?: number;
  side?: string;
  direction?: string;
  status?: string;
}

interface PaperBook {
  positions?: BookPosition[];
  count?: number;
}

interface PortfolioBook {
  positions?: BookPosition[];
}

function flag(value: boolean | undefined, on: string, off: string): string {
  if (value == null) return "—";
  return value ? on : off;
}

function bookLines(rows: BookPosition[] | undefined) {
  return (rows ?? [])
    .filter((row) => row.symbol)
    .map((row) => ({
      symbol: String(row.symbol),
      quantity: Number(row.quantity ?? 0),
    }));
}

export function OperatorScoreboard() {
  const { data: health, error: healthError } = useSWR<ScoreboardHealth>("/health", fetcher, {
    refreshInterval: 15_000,
  });
  const { data: paper, error: paperError } = useSWR<PaperBook>(
    "/portfolio/paper/positions",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: portfolio, error: portfolioError } = useSWR<PortfolioBook>("/portfolio", fetcher, {
    refreshInterval: 15_000,
  });
  const { data: lockout, error: lockoutError } = useSWR<LossTrackerStatus>(
    "/safety/loss-tracker/status",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: gates, error: gatesError } = useSWR<HermesGatesReport>(
    "/api/operator/gates",
    localFetcher,
    { refreshInterval: 15_000 },
  );

  const disagreements =
    paper && portfolio
      ? bookDisagreements(bookLines(portfolio.positions), bookLines(paper.positions))
      : [];
  const paperRows = paper?.positions ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Operator scoreboard</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {healthError ? (
          <UnreachableNote endpoint="/health" />
        ) : (
          <div className="flex flex-wrap gap-2">
            <Badge variant={health?.status === "ok" ? "bull" : "warn"}>
              engine {health?.status ?? "…"}
            </Badge>
            <Badge variant={health?.paper_mode ? "info" : "neutral"}>
              {flag(health?.paper_mode, "paper", "not paper")}
            </Badge>
            <Badge variant={health?.live_trading ? "bear" : "neutral"}>
              {flag(health?.live_trading, "live on", "live off")}
            </Badge>
            <Badge variant={health?.kill_switch_active ? "bear" : "neutral"}>
              {flag(health?.kill_switch_active, "kill on", "kill off")}
            </Badge>
            <Badge variant="neutral">
              IB {health?.ibkr_connected ? "up" : "down"}
              {health?.ibgateway_port != null ? ` ${health.ibgateway_port}` : ""}
            </Badge>
          </div>
        )}

        <div>
          <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
            Open book from /portfolio/paper/positions
          </p>
          {paperError ? (
            <UnreachableNote endpoint="/portfolio/paper/positions" />
          ) : paper == null ? (
            <p className="text-xs text-muted-foreground">…</p>
          ) : paperRows.length === 0 ? (
            <p className="text-xs text-muted-foreground">No open position.</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {paperRows.map((row, index) => (
                <li key={`${row.symbol ?? "row"}-${index}`} className="font-mono">
                  {row.symbol} {row.side ?? row.direction ?? ""} qty {row.quantity ?? 0}
                  {row.status ? ` ${row.status}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
            Book check
          </p>
          {paperError || portfolioError ? (
            <UnreachableNote endpoint="/portfolio" />
          ) : paper == null || portfolio == null ? (
            <p className="text-xs text-muted-foreground">…</p>
          ) : disagreements.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              /portfolio matches /portfolio/paper/positions.
            </p>
          ) : (
            <ul className="space-y-1">
              {disagreements.map((line) => (
                <li key={line}>
                  <Badge variant="warn">{line}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>

        <LockoutBlock lockout={lockout} error={lockoutError} />
        <GatesBlock gates={gates} error={gatesError} />
      </CardContent>
    </Card>
  );
}

export function LockoutBlock({
  lockout,
  error,
}: {
  lockout: LossTrackerStatus | undefined;
  error: unknown;
}) {
  return (
    <div>
      <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Lockout</p>
      {error ? (
        <UnreachableNote endpoint="/safety/loss-tracker/status" />
      ) : lockout == null ? (
        <p className="text-xs text-muted-foreground">…</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={lockout?.is_halted ? "bear" : "neutral"}>
            {lockout?.is_halted ? "halted" : "not halted"}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">
            until {lockout?.halt_until ?? "—"}
          </span>
        </div>
      )}
    </div>
  );
}

export function GatesBlock({
  gates,
  error,
}: {
  gates: HermesGatesReport | undefined;
  error: unknown;
}) {
  return (
    <div>
      <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Hermes gates</p>
      {error ? (
        <UnreachableNote endpoint="/api/operator/gates" />
      ) : gates == null ? (
        <p className="text-xs text-muted-foreground">…</p>
      ) : !gates.found ? (
        <p className="text-xs font-semibold text-warn">{gates.message}</p>
      ) : gates.gates.length === 0 ? (
        <p className="text-xs text-muted-foreground">{gates.message}</p>
      ) : (
        <ul className="space-y-1">
          {gates.fileLockout != null && (
            <li>
              <Badge variant={gates.fileLockout ? "bear" : "neutral"}>
                file lockout {gates.fileLockout ? "on" : "off"}
              </Badge>
            </li>
          )}
          {gates.gates.map((gate) => (
            <li key={gate.name} className="flex items-center gap-2 text-xs">
              <Badge
                variant={gate.status === "pass" ? "bull" : gate.status === "fail" ? "bear" : "warn"}
              >
                {gate.status}
              </Badge>
              <span>{gate.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
