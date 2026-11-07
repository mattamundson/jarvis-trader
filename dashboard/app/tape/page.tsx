"use client";
import { fetchDashboardApi } from "@/lib/api";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtAge } from "@/lib/flowFreshness";
import {
  ageSeconds,
  blocks15,
  fmtNum,
  fmtSigned,
  isTapeStale,
  lastChicagoWallTime,
  levelRows,
  nearestSupportResistance,
  normalizeGex,
  normalizeSnapshot,
  profileAtPrice,
  recentBars,
  tapeAlerts,
  BIG_DELTA,
  TAPE_STALE_AFTER_S,
  VOL_SPIKE_MULT,
  type GexInfo,
  type TapeSnapshot,
} from "@/lib/tapeDerive";
import {
  chartModel,
  mergeLevels,
  normalizePlan,
  planAvailability,
  triggerPanel,
  type ChartModel,
  type PlanAvailability,
  type TapePlan,
  type TriggerEval,
  type TriggerPanel,
} from "@/lib/tapePlan";
import type { MarketStateInfo } from "@/lib/marketSession";
import { tapeEvaluationAllowed } from "@/lib/tapeFreshnessContract";

import TapeExtras from "@/components/tape/TapeExtras";
import { liveBias, todayCT, type LiveBias } from "@/lib/liveBias";

const POLL_MS = 5000;

interface Fetched {
  /** Null = the flow file was readable but carried no usable snapshot (e.g. recorder idle). */
  snap: TapeSnapshot | null;
  /** Age of the snapshot at the moment it was fetched, measured on the server clock. */
  ageAtFetchS: number | null;
  fetchedAtLocal: number;
  plan: TapePlan | null;
  planError: string | null;
  planAvail: PlanAvailability | null;
  recorder: { state: string | null; heartbeatAgeS: number | null; lastTickAgeS: number | null } | null;
  marketState: MarketStateInfo | null;
  gex: GexInfo | null;
  gexError: string | null;
  live: LiveBias | null;
}

const dCls = (n: number) => (n > 0 ? "text-emerald-400" : n < 0 ? "text-red-400" : "text-zinc-400");

export default function TapePage() {
  const [data, setData] = useState<Fetched | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  const [meta, setMeta] = useState<{ source: string | null; sourceBars: string | null; file: string | null; fileAgeS: number | null; stale10m: boolean; gexSource: string | null; gexAgeS: number | null; gexStale: boolean } | null>(null);

  const poll = useCallback(async () => {
    try {
      const body = await fetchDashboardApi<any>("/api/flow/tape");
      setMeta({ source: body?.source ?? null, sourceBars: body?.sourceBars ?? null, file: body?.file ?? null, fileAgeS: typeof body?.fileAgeS === "number" ? body.fileAgeS : null, stale10m: !!body?.stale10m, gexSource: body?.gex?.source ?? null, gexAgeS: typeof body?.gex?.file_age_s === "number" ? body.gex.file_age_s : null, gexStale: !!body?.gex?.stale });
      if (!body?.ok) throw new Error(typeof body?.error === "string" ? body.error : "feed unavailable");
      // A null snapshot (recorder idle, prices null) is NOT an error: keep the recorder/market/plan
      // context so the page can say why there is no data instead of throwing it away.
      const snap = normalizeSnapshot(body.snapshot);
      if (!alive.current) return;
      const serverMs = typeof body.serverEpochMs === "number" ? body.serverEpochMs : Date.now();
      const plan = normalizePlan(body.plan);
      const planError = plan ? null : typeof body.planError === "string" ? body.planError : "plan missing or invalid";
      const rec = body.recorder && typeof body.recorder === "object" ? body.recorder : null;
      const planAvail = planAvailability(plan, {
        todayCt: typeof body.todayCt === "string" ? body.todayCt : null,
        globexTradingDate: typeof body.globexTradingDate === "string" ? body.globexTradingDate : null,
        recorderSessionTradingDay: typeof rec?.sessionTradingDay === "string" ? rec.sessionTradingDay : null,
        recorderLevelsSource: typeof rec?.levelsSource === "string" ? rec.levelsSource : null,
      });
      setData({
        snap,
        ageAtFetchS: snap ? ageSeconds(snap.asOfEpoch, serverMs) : null,
        fetchedAtLocal: Date.now(),
        plan,
        planError,
        planAvail,
        recorder: rec
          ? {
              state: typeof rec.state === "string" ? rec.state : null,
              heartbeatAgeS: typeof rec.heartbeatAgeS === "number" ? rec.heartbeatAgeS : null,
              lastTickAgeS: typeof rec.lastTickAgeS === "number" ? rec.lastTickAgeS : null,
            }
          : null,
        marketState: body.marketState && typeof body.marketState === "object" ? body.marketState : null,
        gex: normalizeGex(body.gex, serverMs),
        gexError: typeof body.gexError === "string" ? body.gexError : null,
        live: snap
          ? liveBias({ last: snap.price.last ?? null, vwap: snap.price.vwap ?? null, gateCvd: body.snapshot?.gate_cvd, nqRel: body.snapshot?.nq?.rel, netGex: body.gex?.net_gex })
          : null,
      });
      setFetchError(null);
    } catch (e) {
      if (alive.current) setFetchError(e instanceof Error ? e.message : "fetch failed");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    poll();
    const p = setInterval(poll, POLL_MS);
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => {
      alive.current = false;
      clearInterval(p);
      clearInterval(t);
    };
  }, [poll]);

  // Age keeps counting between polls, so a dead feed turns STALE on its own.
  const age = useMemo(() => {
    if (!data || data.ageAtFetchS === null) return null;
    return data.ageAtFetchS + Math.floor((Date.now() - data.fetchedAtLocal) / 1000);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, tick]);

  // Age of the last ACTUAL tick (not the 5s heartbeat write). Null = no tick recorded this window;
  // a ticking heartbeat must never make an absent tick look current.
  const tickAge = useMemo(() => {
    if (!data?.recorder || data.recorder.lastTickAgeS === null) return null;
    return data.recorder.lastTickAgeS + Math.floor((Date.now() - data.fetchedAtLocal) / 1000);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, tick]);

  const snap = data?.snap ?? null;
  const plan = data?.plan ?? null;
  const planAvail = data?.planAvail ?? null;
  const gex = data?.gex ?? null;
  const stale = !tapeEvaluationAllowed(!!snap, age, tickAge, fetchError !== null, TAPE_STALE_AFTER_S);

  const derived = useMemo(() => {
    if (!snap) return null;
    const last = snap.price.last;
    const since = lastChicagoWallTime(snap.asOfEpoch ?? snap.bars[snap.bars.length - 1]?.t ?? Math.floor(Date.now() / 1000), 5, 30);
    const profile = profileAtPrice(snap.bars, since);
    const eligiblePlan = !stale && planAvail?.usable ? plan : null;
    const merged = mergeLevels(mergeLevels(snap.levels, gex?.levels ?? []), eligiblePlan?.extraLevels ?? []);
    const lv = levelRows(merged, last);
    const lastP = Math.round(last);
    const ladder = profile.some((r) => r.price === lastP)
      ? profile
      : [...profile, { price: lastP, vol: 0, delta: 0, bars: 0 }].sort((a, b) => b.price - a.price);
    return {
      merged,
      ladder,
      // Trigger evaluation only against a plan of record that passed the availability gate.
      panel: eligiblePlan ? triggerPanel(snap, eligiblePlan) : null,
      chart: chartModel({ snap, levels: merged, plan: eligiblePlan }),
      bars: recentBars(snap.bars, 60).reverse(),
      blocks: blocks15(snap.bars).reverse(),
      profile,
      maxVol: Math.max(1, ...profile.map((r) => r.vol).filter(Number.isFinite)),
      maxAbsDelta: Math.max(1, ...profile.map((r) => Math.abs(r.delta)).filter(Number.isFinite)),
      levels: lv,
      sr: nearestSupportResistance(lv),
      alerts: tapeAlerts(snap),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap, plan, planAvail, gex, stale]);

  const vwapDist = snap && snap.price.vwap !== null ? snap.price.last - snap.price.vwap : null;
  const nq30 = snap?.nq.windows["30m"] ?? null;
  const rec = data?.recorder ?? null;
  const marketState = data?.marketState ?? null;
  // Closure is asserted ONLY from the schedule contract; recorder idleness alone never implies it.
  const marketLabel = (() => {
    if (!marketState || marketState.state === "unknown") return "market state unknown (not asserted)";
    if (marketState.state === "scheduled_closed") return `closed per schedule — ${marketState.detail}`;
    const idle = !rec?.state || rec.state.toLowerCase().includes("idle");
    return idle ? `recorder idle — schedule says OPEN window (${marketState.detail})` : `open per schedule (${marketState.detail})`;
  })();

  return (
    <main className="min-h-screen bg-black p-3 font-mono text-[12px] text-zinc-200">
      {stale && (
        <div role="alert" data-testid="stale-banner" className="mb-2 rounded border border-red-600 bg-red-950 px-3 py-2 text-sm font-bold text-red-200">
          STALE{" "}
          {!snap
            ? `- no data yet${fetchError ? ` (${fetchError})` : ""}`
            : fetchError
              ? `- feed error: ${fetchError}. Showing last good snapshot (${fmtAge(age)}).`
              : `- snapshot ${fmtAge(age)}, last tick ${fmtAge(tickAge)} (limit ${TAPE_STALE_AFTER_S}s). Do not read these numbers as live.`}
        </div>
      )}

      <h1 className="mb-1 text-sm font-bold tracking-wide text-zinc-300">ES TAPE <span className="font-normal text-zinc-500">(paper, readout only, refreshes every 5s)</span></h1>

      <div data-testid="tape-source" className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        {meta?.stale10m && <span data-testid="stale-10m-badge" className="rounded bg-red-600 px-2 py-0.5 font-bold text-white">STALE &gt;10 min</span>}
        <span>Tape source: <b className="text-zinc-200">{meta?.source ?? "unknown"}</b>{meta?.sourceBars ? ` (bars: ${meta.sourceBars})` : ""}{meta?.file === "box-fallback" ? " [box fallback file]" : ""}{meta && meta.fileAgeS !== null ? ` | file age ${fmtAge(meta.fileAgeS)}` : ""}</span>
        <span>| GEX source: <b className="text-zinc-200">{meta?.gexSource ?? "unknown"}</b>{meta && meta.gexAgeS !== null ? ` (${fmtAge(meta.gexAgeS)})` : ""}{meta?.gexStale && <span className="ml-1 rounded bg-red-600 px-1 font-bold text-white">STALE</span>}</span>
      </div>

      {/* Recorder liveness + market state: heartbeat (file writes) and last actual tick are
          deliberately reported separately, so a ticking heartbeat cannot masquerade as a live tick. */}
      <div data-testid="tape-recorder-market" className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        <span data-testid="tape-recorder-state">
          Recorder: <b className="text-zinc-200">{rec?.state ?? "unknown"}</b>
          {rec?.heartbeatAgeS !== null && rec?.heartbeatAgeS !== undefined ? ` | heartbeat ${fmtAge(rec.heartbeatAgeS)}` : ""}
          {rec?.lastTickAgeS !== null && rec?.lastTickAgeS !== undefined ? ` | last tick ${fmtAge(rec.lastTickAgeS)}` : " | last tick: none this window"}
        </span>
        <span data-testid="tape-market-state">| Market: {marketLabel}</span>
      </div>

      <TapeExtras />

      {/* Render the plan box even without a usable snapshot: a stale/wrong-session/conflicting
          plan must be visible while the market is closed, not only once data returns. */}
      {(snap || plan) && <TriggerBox panel={derived?.panel ?? null} plan={plan} planError={data?.planError ?? null} planAvail={planAvail} stale={stale} live={data?.live ?? null} />}

      {/* Header */}
      <div data-testid="tape-header" className="mb-2 grid grid-cols-2 gap-2 rounded border border-zinc-800 bg-zinc-950 p-2 sm:grid-cols-4 lg:grid-cols-8">
        <Stat label="ES last" value={snap ? fmtNum(snap.price.last) : "--"} big />
        <Stat label="Session hi / lo" value={snap ? `${fmtNum(snap.price.hi)} / ${fmtNum(snap.price.lo)}` : "--"} />
        <Stat label="VWAP" value={snap ? fmtNum(snap.price.vwap) : "--"} sub={vwapDist !== null ? `${fmtSigned(vwapDist, 2)} pts` : undefined} />
        <Stat label="CVD" value={snap ? fmtSigned(snap.cvd) : "--"} cls={snap && snap.cvd !== null ? dCls(snap.cvd) : ""} />
        <Stat label="NQ last" value={snap ? fmtNum(snap.nq.last) : "--"} />
        <Stat label="NQ lead" value={snap?.nq.lead ?? "--"} sub={nq30 && nq30.rs !== null ? `30m RS ${fmtSigned(nq30.rs, 3)}` : undefined} />
        <Stat label="As of (CT)" value={snap?.asOfCt ? snap.asOfCt.slice(11, 19) : "--"} />
        <Stat
          label="Last tick age"
          value={tickAge !== null ? fmtAge(tickAge) : "no tick"}
          sub={rec ? `heartbeat ${rec.heartbeatAgeS !== null ? fmtAge(rec.heartbeatAgeS) : "?"} / file ${meta?.fileAgeS !== null && meta?.fileAgeS !== undefined ? fmtAge(meta.fileAgeS) : "?"}` : undefined}
          cls={tickAge === null || tickAge > TAPE_STALE_AFTER_S ? "text-red-400" : "text-emerald-400"}
        />
      </div>

      {/* Alerts */}
      <div data-testid="tape-alerts" className="mb-2 rounded border border-zinc-800 bg-zinc-950 px-3 py-1.5">
        {!derived || stale ? (
          // With no usable snapshot there is no basis to evaluate divergence — never render the
          // "no divergence" all-clear line (it reads as an analytical conclusion on zero data).
          <div data-testid="tape-alerts-unevaluated" className="text-zinc-500">
            No data — divergence not evaluated. Fresh tick and snapshot evidence required.
          </div>
        ) : derived.alerts.length > 0 ? (
          derived.alerts.map((a) => (
            <div key={a.kind} className="text-amber-300">
              ! {a.text}
            </div>
          ))
        ) : (
          <div className="text-zinc-500">No alert thresholds detected in the available inputs; this does not establish complete CVD/NQ agreement.</div>
        )}
      </div>

      {derived?.chart && snap && (
        <Panel title={`1-minute chart, last ${derived.chart.count} bars (delta underneath, amber outline = absorption)`} testid="tape-chart">
          <MiniChart m={derived.chart} />
        </Panel>
      )}

      {derived && snap && (
        <div className="mt-2 grid gap-2 lg:grid-cols-3">
          {/* Last 15 bars */}
          <Panel title={`Last 60 minutes (DELTA: |delta| >= ${BIG_DELTA}, VOL: >= ${VOL_SPIKE_MULT}x 20-bar avg, ABSORB: big delta but bar closed against it)`} testid="tape-bars" fill>
            <div className="absolute inset-0 overflow-y-auto">
            <table className="w-full text-right">
              <thead className="text-zinc-500">
                <tr>
                  <th className="text-left">CT</th>
                  <th>Close</th>
                  <th>Rng</th>
                  <th>Chg</th>
                  <th>Vol</th>
                  <th>Delta</th>
                  <th>CVD</th>
                  <th className="text-left pl-2">Flag</th>
                </tr>
              </thead>
              <tbody>
                {derived.bars.map((b) => (
                  <tr key={b.t} className={b.absorb ? "bg-amber-950" : b.bigDelta || b.volSpike ? "bg-zinc-900" : ""}>
                    <td className="text-left text-zinc-400">{b.time}</td>
                    <td>{fmtNum(b.close)}</td>
                    <td>{fmtNum(b.range)}</td>
                    <td className={dCls(b.move)}>{fmtSigned(b.move, 2)}</td>
                    <td className={b.volSpike ? "font-bold text-amber-300" : ""}>{fmtNum(b.vol, 0)}</td>
                    <td className={`${dCls(b.delta)} ${b.bigDelta ? "font-bold" : ""}`}>{fmtSigned(b.delta)}</td>
                    <td className={dCls(b.cvd)}>{fmtSigned(b.cvd)}</td>
                    <td className="pl-2 text-left text-amber-300">
                      {b.bigDelta ? "DELTA " : ""}
                      {b.volSpike ? "VOL " : ""}
                      {b.absorb ? (
                        <span className="font-bold text-orange-300" title={b.absorb === "up" ? "Positive delta but price closed lower: buying absorbed" : "Negative delta but price closed higher: selling absorbed"}>
                          ABSORB {b.absorb === "up" ? "buys" : "sells"}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </Panel>

          {/* Volume and delta at price */}
          <Panel title="Volume / delta at price since 05:30 CT (close rounded to point, current price marked)" testid="tape-profile" fill>
            <div className="absolute inset-x-0 top-0 bottom-5 overflow-y-auto">
              {derived.profile.length === 0 && <div className="text-zinc-500">No bars since 05:30 CT.</div>}
              {derived.ladder.map((r) => {
                const isLast = Math.round(snap.price.last) === r.price;
                const tags = derived.levels.filter((l) => Math.round(l.px) === r.price).map((l) => l.name);
                return (
                  <div key={r.price} data-price-row={isLast ? "true" : undefined} className={`flex items-center gap-2 ${isLast ? "border-y border-sky-500 bg-sky-950" : ""}`}>
                    <span className={`w-12 text-right ${isLast ? "font-bold text-white" : "text-zinc-400"}`}>{r.price}</span>
                    <div className="relative h-3 flex-1 bg-zinc-900">
                      <div className="absolute inset-y-0 left-0 bg-sky-700" style={{ width: `${Number.isFinite(r.vol) ? (r.vol / derived.maxVol) * 100 : 0}%` }} />
                      <div
                        className={`absolute inset-y-1 left-0 ${r.delta >= 0 ? "bg-emerald-400" : "bg-red-400"}`}
                        style={{ width: `${Number.isFinite(r.delta) ? (Math.abs(r.delta) / derived.maxAbsDelta) * 100 : 0}%` }}
                      />
                    </div>
                    <span className="w-14 text-right text-zinc-300">{fmtNum(r.vol, 0)}</span>
                    <span className={`w-12 text-right ${dCls(r.delta)}`}>{fmtSigned(r.delta)}</span>
                    <span className="w-28 truncate text-[10px] text-sky-300">
                      {isLast ? `<< ES ${fmtNum(snap.price.last)}` : tags.length ? tags.join(", ") : ""}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="absolute inset-x-0 bottom-0 text-[10px] text-zinc-500">blue = volume, green/red = net delta (scaled separately)</div>
          </Panel>

          <div className="space-y-2">
            {/* Levels */}
            <Panel title="Levels" testid="tape-levels">
              <div data-testid="tape-gex" className={`mb-1 ${!gex || gex.stale ? "text-amber-300" : "text-zinc-300"}`}>
                {gex ? (
                  <>
                    Gamma (ZeroGEX, ~15-20m delayed) as of {gex.asOfCt ?? "?"} CT, age {gex.ageMin === null ? "?" : `${gex.ageMin}m`}
                    {gex.stale ? " STALE" : ""}: flip {fmtNum(gex.flip)} | call wall {fmtNum(gex.callWall)} | put wall {fmtNum(gex.putWall)} | max pain {gex.maxPain === null ? "n/a" : fmtNum(gex.maxPain)}
                  </>
                ) : (
                  <>Gamma levels n/a{data?.gexError ? `: ${data.gexError}` : ""} | max pain: n/a</>
                )}
              </div>
              <div data-testid="tape-sr-state" className="mb-1 text-sky-300">
                {derived.sr.state}
              </div>
              <div data-testid="tape-sr-next" className="mb-1 text-zinc-300">
                Next resistance: {derived.sr.resistance ? `${derived.sr.resistance.name} ${derived.sr.resistance.px} (${fmtSigned(derived.sr.resistance.dist, 2)})` : "none above"}
                {" | "}
                Next support: {derived.sr.support ? `${derived.sr.support.name} ${derived.sr.support.px} (${fmtSigned(derived.sr.support.dist, 2)})` : "none below"}
              </div>
              <table className="w-full text-right">
                <thead className="text-zinc-500">
                  <tr>
                    <th className="text-left">Level</th>
                    <th>Px</th>
                    <th>Dist</th>
                    <th className="text-left pl-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {derived.levels.map((l, i) => {
                    const isS = derived.sr.support === l;
                    const isR = derived.sr.resistance === l;
                    const showPrice = l.dist <= 0 && (i === 0 || derived.levels[i - 1].dist > 0);
                    return (
                      <Fragment key={`${l.name}-${l.px}-${i}`}>
                      {showPrice && (
                        <tr data-testid="tape-levels-price" className="border-y border-sky-500 bg-sky-950 font-bold text-white">
                          <td className="text-left">ES now</td>
                          <td>{fmtNum(snap.price.last)}</td>
                          <td></td>
                          <td></td>
                        </tr>
                      )}
                      <tr className={isS || isR ? "bg-zinc-900" : ""}>
                        <td className="text-left text-zinc-300">
                          {l.name}
                          {isR ? " (R)" : isS ? " (S)" : ""}
                        </td>
                        <td>{fmtNum(l.px)}</td>
                        <td className={l.dist > 0 ? "text-red-300" : "text-emerald-300"}>{fmtSigned(l.dist, 2)}</td>
                        <td className="pl-2 text-left text-zinc-500">{l.status ?? ""}</td>
                      </tr>
                      </Fragment>
                    );
                  })}
                  {derived.levels.length > 0 && derived.levels.every((l) => l.dist > 0) && (
                    <tr data-testid="tape-levels-price" className="border-y border-sky-500 bg-sky-950 font-bold text-white">
                      <td className="text-left">ES now</td>
                      <td>{fmtNum(snap.price.last)}</td>
                      <td></td>
                      <td></td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>

            {/* 15 minute blocks */}
            <Panel title="15-minute blocks (newest first)" testid="tape-blocks">
              <div className="max-h-[220px] overflow-y-auto">
                <table className="w-full text-right">
                  <thead className="text-zinc-500">
                    <tr>
                      <th className="text-left">CT</th>
                      <th>Vol</th>
                      <th>Net delta</th>
                      <th>Close</th>
                    </tr>
                  </thead>
                  <tbody>
                    {derived.blocks.map((b) => (
                      <tr key={b.start}>
                        <td className="text-left text-zinc-400">
                          {b.label}
                          {b.partial ? "*" : ""}
                        </td>
                        <td>{fmtNum(b.vol, 0)}</td>
                        <td className={dCls(b.delta)}>{fmtSigned(b.delta)}</td>
                        <td>{fmtNum(b.close)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-1 text-[10px] text-zinc-500">* partial block</div>
            </Panel>
          </div>
        </div>
      )}

      <footer className="mt-3 text-center text-sm font-bold text-zinc-300" data-testid="tape-footer">
        Live legal? NO, size 0
      </footer>
    </main>
  );
}

function Stat({ label, value, sub, cls = "", big = false }: { label: string; value: string; sub?: string; cls?: string; big?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-zinc-500">{label}</div>
      <div className={`${big ? "text-xl" : "text-base"} font-bold ${cls}`}>{value}</div>
      {sub && <div className="text-[10px] text-zinc-400">{sub}</div>}
    </div>
  );
}

function Panel({ title, testid, children, fill }: { title: string; testid: string; children: React.ReactNode; fill?: boolean }) {
  return (
    <section data-testid={testid} className={`rounded border border-zinc-800 bg-zinc-950 p-2 ${fill ? "flex h-full flex-col" : ""}`}>
      <h2 className="mb-1 text-[11px] font-bold uppercase text-zinc-400">{title}</h2>
      {fill ? <div className="relative min-h-[420px] flex-1">{children}</div> : children}
    </section>
  );
}
const STATUS_CLS: Record<string, string> = {
  ARMED: "border-amber-500 bg-amber-950 text-amber-200",
  TRIGGERED: "border-emerald-400 bg-emerald-950 text-emerald-200",
  FAILED: "border-red-500 bg-red-950 text-red-200",
};

const VOTE_CLS: Record<string, string> = { up: "text-emerald-400", down: "text-red-400", flat: "text-zinc-400", "n/a": "text-zinc-500" };
const BIAS_CLS: Record<string, string> = { BULL: "text-emerald-300", BEAR: "text-red-300", MIXED: "text-amber-200" };

function LiveBiasLine({ live, stale }: { live: LiveBias | null; stale: boolean }) {
  if (!live) return <div data-testid="tape-bias" className="mb-2 text-sm font-bold text-zinc-400">BIAS: n/a (no live data)</div>;
  return (
    <div data-testid="tape-bias" data-bias={live.bias} className="mb-2">
      <div className="text-sm font-bold">
        <span className="text-sky-200">BIAS (live): </span>
        <span className={BIAS_CLS[live.bias]}>{live.bias}</span>
        {stale && <span className="ml-2 text-red-400">(STALE, not live)</span>}
      </div>
      <div data-testid="tape-bias-votes" className="text-[11px] text-zinc-300">
        {live.inputs.map((i) => (
          <span key={i.name} className="mr-3">
            {i.name}: <span className={VOTE_CLS[i.vote]}>{i.vote.toUpperCase()}</span> <span className="text-zinc-500">({i.detail})</span>
          </span>
        ))}
        <span data-testid="tape-bias-gamma" className={live.gamma.sign === "short" ? "text-amber-300" : "text-zinc-400"}>
          Context: {live.gamma.note}
          {live.gamma.netGex !== null ? ` (net GEX ${live.gamma.raw})` : ""}
        </span>
      </div>
    </div>
  );
}

function TriggerBox({ panel, plan, planError, planAvail, stale, live }: { panel: TriggerPanel | null; plan: TapePlan | null; planError: string | null; planAvail: PlanAvailability | null; stale: boolean; live: LiveBias | null }) {
  if (!plan) {
    return (
      <section data-testid="tape-triggers" className="mb-2 rounded border border-amber-600 bg-zinc-950 p-2 text-amber-300">
        <LiveBiasLine live={live} stale={stale} />
        No trigger plan loaded (config/tape-plan.json): {planError ?? "not loaded"}. Triggers are off until the plan file is valid.
      </section>
    );
  }
  // A stale, wrong-session, or plan-source-conflicting plan is NEVER evaluated for actionable
  // triggers: statuses are withheld and the plan is shown as historical reference only. The
  // dashboard does not auto-pick between the dashboard config plan and the recorder's plan of record.
  if (planAvail && !planAvail.usable) {
    return (
      <section data-testid="tape-triggers" className="mb-2 rounded border border-red-600 bg-zinc-950 p-2 text-red-200">
        <LiveBiasLine live={live} stale={stale} />
        <div data-testid="tape-plan-unavailable" className="text-xs font-bold">
          PLAN UNAVAILABLE FOR TRIGGERS: {planAvail.reason}
        </div>
        <div className="mt-1 text-[10px] text-zinc-400">
          No ARMED/TRIGGERED/FAILED status is evaluated against a stale, wrong-session, or conflicting plan. Resolve the plan of record at the source; the dashboard will not choose one for you.
        </div>
        <div data-testid="tape-plan-historical" className="mt-1 text-[11px] text-zinc-400">
          Historical reference only — not actionable. Plan dated {plan.date ?? "(no date)"}
          {plan.note ? `, ${plan.note}` : ""}
          {plan.long ? `; long trigger ${plan.long.trigger}${plan.long.targets.length ? `, targets ${plan.long.targets.join("/")}` : ""}` : ""}
          {plan.short ? `; short trigger ${plan.short.trigger}${plan.short.targets.length ? `, targets ${plan.short.targets.join("/")}` : ""}` : ""}
          {plan.extraLevels.length ? `; ${plan.extraLevels.length} plan level(s)` : ""}.
        </div>
      </section>
    );
  }
  const planToday = plan.date === todayCT();
  if (!panel) {
    return (
      <section data-testid="tape-triggers" className="mb-2 rounded border border-amber-600 bg-zinc-950 p-2 text-amber-300">
        <LiveBiasLine live={live} stale={stale} />
        Plan present but evaluation unavailable: tick/snapshot evidence or plan checks are not current. Triggers remain off.
      </section>
    );
  }
  return (
    <section data-testid="tape-triggers" className={`mb-2 rounded border border-zinc-700 bg-zinc-950 p-2 ${stale ? "opacity-60" : ""}`}>
      <LiveBiasLine live={live} stale={stale} />
      <div data-testid="tape-plan-head" className="mb-1 text-xs font-bold text-zinc-300">
        Plan ({plan.date ?? "no date"}{plan.note ? `, ${plan.note}` : ""}) - plan check: {panel.bias}
        {!planToday && <span data-testid="tape-plan-not-today" className="ml-2 rounded border border-red-600 bg-red-950 px-1 text-red-200">PLAN NOT TODAY</span>}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {panel.long && <TriggerCard ev={panel.long} testid="tape-trigger-long" />}
        {panel.short && <TriggerCard ev={panel.short} testid="tape-trigger-short" />}
      </div>
      <div className="mt-1 text-[10px] text-zinc-500">
        Plan {plan.date ?? ""} {plan.note ? `- ${plan.note}` : ""} (edit config/tape-plan.json, picked up within 5s). Paper readout, not an order signal.
      </div>
    </section>
  );
}

function TriggerCard({ ev, testid }: { ev: TriggerEval; testid: string }) {
  return (
    <div data-testid={testid} data-status={ev.status} className="rounded border border-zinc-800 p-2">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-bold uppercase text-zinc-200">{ev.side}</span>
        <span className={`rounded border px-2 py-0.5 text-xs font-bold ${STATUS_CLS[ev.status]}`}>{ev.status}</span>
        <span className="text-zinc-500">{ev.reason}</span>
      </div>
      {ev.reArmedNote && (
        <div data-testid={`${testid}-rearmed`} className="mb-1 text-[10px] text-zinc-500">
          {ev.reArmedNote}
        </div>
      )}
      <div className="mb-1 text-zinc-300">{ev.ifThen}</div>
      <ul className="space-y-0.5">
        {ev.checks.map((c) => (
          <li key={c.label} className={c.ok ? "text-emerald-300" : "text-zinc-500"}>
            [{c.ok ? "x" : " "}] {c.label} <span className="text-zinc-500">- {c.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const LINE_CLS: Record<string, { stroke: string; dash?: string; text: string }> = {
  vwap: { stroke: "#f59e0b", dash: "5 3", text: "#f59e0b" },
  level: { stroke: "#52525b", dash: "2 3", text: "#a1a1aa" },
  trigger: { stroke: "#38bdf8", dash: "6 3", text: "#7dd3fc" },
  price: { stroke: "#ffffff", text: "#ffffff" },
};

function MiniChart({ m }: { m: ChartModel }) {
  // Keep right-hand labels from overlapping: sort by y and push down at least 10px apart.
  const sorted = [...m.lines].sort((a, b) => a.y - b.y);
  let prev = -100;
  const labels = sorted.map((l) => {
    const y = Math.max(l.y, prev + 10);
    prev = y;
    return { ...l, ly: y };
  });
  return (
    <svg data-testid="tape-chart-svg" viewBox={`0 0 ${m.width} ${m.height}`} className="w-full" role="img" aria-label="ES 1-minute chart with delta bars">
      {m.lines.map((l, i) => {
        const c = LINE_CLS[l.kind];
        return <line key={i} x1={0} x2={m.plotRight} y1={l.y} y2={l.y} stroke={c.stroke} strokeWidth={l.kind === "price" ? 1 : 0.8} strokeDasharray={c.dash} opacity={0.8} />;
      })}
      {m.candles.map((c, i) => {
        const col = c.up ? "#34d399" : "#f87171";
        const top = Math.min(c.yO, c.yC);
        const h = Math.max(1, Math.abs(c.yC - c.yO));
        return (
          <g key={i}>
            <line x1={c.x} x2={c.x} y1={c.yH} y2={c.yL} stroke={col} strokeWidth={1} />
            <rect x={c.x - c.w / 2} y={top} width={c.w} height={h} fill={col} stroke={c.absorb ? "#fb923c" : "none"} strokeWidth={c.absorb ? 1.5 : 0} />
          </g>
        );
      })}
      <line x1={0} x2={m.plotRight} y1={m.deltaZeroY} y2={m.deltaZeroY} stroke="#3f3f46" strokeWidth={0.8} />
      {m.deltaBars.map((d, i) => (
        <rect key={i} x={d.x - d.w / 2} y={d.y} width={d.w} height={d.h} fill={d.pos ? "#34d399" : "#f87171"} opacity={d.big ? 1 : 0.5} />
      ))}
      {labels.map((l, i) => (
        <text key={i} x={m.labelX} y={l.ly + 3} fontSize={10} fill={LINE_CLS[l.kind].text} fontFamily="monospace">
          {l.label}
        </text>
      ))}
      {m.timeLabels.map((t, i) => (
        <text key={i} x={t.x} y={m.height - 2} fontSize={9} fill="#71717a" textAnchor="middle" fontFamily="monospace">
          {t.text}
        </text>
      ))}
    </svg>
  );
}
