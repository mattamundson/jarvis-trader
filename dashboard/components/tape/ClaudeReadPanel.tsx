"use client";

import { useEffect, useState } from "react";
import { fetchDashboardApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  SIGNAL_NOT_A_FILL,
  claudeReadBadge,
  claudeReadFreshness,
  gammaFreshness,
  type ClaudeReadPayload,
  type ClaudeReadTrigger,
  type ClaudeTriggerStatus,
} from "@/lib/tape/claudeRead";

const POLL_MS = 5000;

function px(n: number | null | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? String(n) : "--";
}

function statusVariant(status: ClaudeTriggerStatus): "warn" | "info" | "neutral" {
  switch (status) {
    case "armed":
      return "warn";
    case "signal":
      return "info";
    case "invalidated":
      return "neutral";
    default: {
      const neverStatus: never = status;
      return neverStatus;
    }
  }
}

function TriggerRow({ trigger }: { trigger: ClaudeReadTrigger }) {
  return (
    <li data-testid="claude-read-trigger" className="rounded border border-zinc-800 px-2 py-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-bold text-zinc-100">{trigger.name}</span>
        <Badge variant={statusVariant(trigger.status)}>{trigger.status}</Badge>
        <span className="text-zinc-300">
          {trigger.direction} {px(trigger.level)} · closes {px(trigger.closes_seen)}/{px(trigger.closes_needed)}
        </span>
      </div>
      <div data-testid="signal-not-a-fill" className="text-[11px] font-bold text-amber-200">{SIGNAL_NOT_A_FILL}</div>
    </li>
  );
}

export default function ClaudeReadPanel() {
  const [body, setBody] = useState<ClaudeReadPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      // Advance the clock even when the request fails, so a held read can age out of CURRENT.
      setNow(Date.now());
      try {
        const next = await fetchDashboardApi<ClaudeReadPayload>("/api/tape/claude-read");
        if (alive) {
          setBody(next);
          setFailed(false);
        }
      } catch {
        if (alive) setFailed(true);
      }
    };
    pull();
    const timer = setInterval(pull, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const read = body?.read ?? null;
  const fresh = read ? claudeReadFreshness(read.written_at, now) : null;
  const gamma = read?.context.gamma
    ? { ...gammaFreshness(read.context.gamma.as_of, now), present: true }
    : null;
  const badge = claudeReadBadge(failed, fresh);
  const frame = badge === "stale"
    ? "border-red-600 bg-red-950"
    : badge === "refresh-failed"
      ? "border-amber-500 bg-amber-950"
      : "border-zinc-700 bg-zinc-950";

  return (
    <section data-testid="claude-read-panel" className={`mb-2 rounded border p-2 ${frame}`}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-bold tracking-wide text-zinc-100">Claude read</h2>
        {badge === "stale" && <Badge variant="bear" data-testid="claude-read-stale">STALE</Badge>}
        {badge === "current" && <Badge variant="info" data-testid="claude-read-fresh">CURRENT</Badge>}
        {badge === "refresh-failed" && <Badge variant="warn" data-testid="claude-read-refresh-failed">REFRESH FAILED</Badge>}
        <span className="text-[10px] text-zinc-500">read-only · {SIGNAL_NOT_A_FILL}</span>
      </div>

      {failed && (
        <p data-testid="claude-read-error">
          {read ? "Claude read could not be refreshed. Not confirmed current." : "Claude read could not be loaded."}
        </p>
      )}
      {!failed && !body && <p className="text-zinc-400">Reading claude-read-latest.json…</p>}
      {body?.missing && <p data-testid="claude-read-missing">{body.error}</p>}
      {body?.malformed && <p data-testid="claude-read-malformed">{body.error}</p>}

      {read && fresh && (
        <div className="space-y-2">
          {badge === "stale" && (
            <div role="alert" className="rounded border border-red-500 bg-red-900 px-2 py-1 text-sm font-bold text-red-100">
              STALE — {fresh.reason}
            </div>
          )}
          {badge !== "stale" && <p className="text-[11px] text-zinc-400">{fresh.reason}</p>}
          <p data-testid="claude-read-written-at">
            written {fresh.writtenAtCt ?? read.written_at} · kind {read.kind}{read.source ? ` · source ${read.source}` : ""}
          </p>
          <div data-testid="claude-read-context" className="rounded border border-zinc-800 p-2">
            <div className="mb-1 font-bold text-zinc-300">Context</div>
            {read.context.prior_sessions.length === 0 && <div className="text-zinc-500">No prior sessions in this read.</div>}
            <ul>
              {read.context.prior_sessions.map((session) => (
                <li key={session.date}>
                  {session.date} close {px(session.close)} low {px(session.low)}
                  {session.close_note ? ` — ${session.close_note}` : ""}
                </li>
              ))}
            </ul>
            <div>VIX regime: {read.context.vix_regime ?? "--"}</div>
            <div>Event implied move: {read.context.event_implied_move ?? "--"}</div>
            {read.context.gamma && gamma?.present ? (
              <div data-testid="claude-read-gamma" className="mt-1 text-sm font-bold">
                Gamma {read.context.gamma.regime ?? "unknown"} · flip {px(read.context.gamma.flip)} · pin {px(read.context.gamma.pin)}
                {" · as of "}{gamma.asOfCt ?? "unknown"}{gamma.ageMinutes !== null ? ` (${gamma.ageMinutes} min)` : ""}
                {gamma.stale && <Badge variant="bear" data-testid="claude-read-gamma-stale" className="ml-2">GAMMA STALE</Badge>}
                {gamma.stale && <span className="ml-2 text-red-200">{gamma.reason}</span>}
              </div>
            ) : (
              <div data-testid="claude-read-gamma">Gamma: not in this read</div>
            )}
            {read.context.stale.length > 0 && (
              <div data-testid="claude-read-stale-inputs" className="mt-1">
                <div className="font-bold text-amber-200">Stale inputs in this read</div>
                <ul>{read.context.stale.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}
          </div>
          <p data-testid="claude-read-bias"><span className="font-bold text-zinc-300">Bias: </span>{read.bias ?? "--"}</p>
          <p data-testid="claude-read-plan" className="whitespace-pre-wrap"><span className="font-bold text-zinc-300">Plan: </span>{read.plan ?? "--"}</p>
          <div>
            <div className="font-bold text-zinc-300">Levels</div>
            {read.levels.length === 0 && <div className="text-zinc-500">No levels in this read.</div>}
            <ul>
              {read.levels.map((level) => (
                <li key={`${level.price}-${level.label ?? ""}`}>{px(level.price)}{level.label ? ` — ${level.label}` : ""}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="font-bold text-zinc-300">Triggers</div>
            {read.triggers.length === 0 && <div className="text-zinc-500">No triggers in this read.</div>}
            <ul className="space-y-1">
              {read.triggers.map((trigger) => <TriggerRow key={`${trigger.name}-${trigger.level}-${trigger.direction}`} trigger={trigger} />)}
            </ul>
          </div>
          {read.note && <p className="text-zinc-400">{read.note}</p>}
          {read.live_legal && <p data-testid="claude-read-live-legal">live legal: {read.live_legal}</p>}
        </div>
      )}
    </section>
  );
}
