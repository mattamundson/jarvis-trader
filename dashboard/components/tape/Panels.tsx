"use client";

import type { FlowOut, GexOut, LevelSourceOut, SourceEnvelope, TapePayload } from "@/lib/tape/serialize";
import { freshnessLevel } from "@/lib/tape/time";
import { ageSeconds, FreshChip, StaleBanner } from "./Fresh";
import { C, ctHM, MONO, nf } from "./theme";

export function Panel({ title, right, children, className = "", testId }: { title: string; right?: React.ReactNode; children: React.ReactNode; className?: string; testId?: string }) {
  return (
    <section data-testid={testId} className={`border ${className}`} style={{ borderColor: C.line, background: C.panel }}>
      <header className="flex items-center justify-between gap-2 border-b px-2 py-1" style={{ borderColor: C.line }}>
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em]" style={{ color: C.dim }}>{title}</h2>
        {right}
      </header>
      <div className="p-2">{children}</div>
    </section>
  );
}

const dash = <span style={{ color: C.dim }}>—</span>;

// ------------------------------------------------------------------------------------ status bar
export function StatusBar({ payload, nowMs }: { payload: TapePayload | undefined; nowMs: number }) {
  const flow = payload?.flow.data ?? null;
  const flowAge = ageSeconds(payload?.flow.as_of_ms, nowMs);
  const recAge = flow?.recorder?.heartbeat_age_s != null && flowAge != null ? flow?.recorder?.heartbeat_age_s + flowAge : null;
  const nqAge = ageSeconds(flow?.nq?.as_of_epoch != null ? flow?.nq?.as_of_epoch * 1000 : null, nowMs);
  const bias = flow?.bias?.label ?? null;
  const biasColor = bias === "BULL" ? C.green : bias === "BEAR" ? C.red : bias ? C.amber : C.dim;
  const trig = flow?.trigger ?? null;
  const trigColor = trig?.state === "confirmed" ? C.green : trig?.state === "pressing" ? C.amber : C.dim;
  const p = flow?.price;
  const src = (e: SourceEnvelope<unknown> | undefined) => ageSeconds(e?.as_of_ms, nowMs);
  return (
    <div data-testid="status-bar" className="col-span-12 flex flex-wrap items-center gap-x-4 gap-y-2 border px-3 py-2" style={{ borderColor: C.line, background: C.panel }}>
      <h1 className="text-[13px] font-bold tracking-[0.2em]" style={{ color: C.text }}>TAPE · ORDER FLOW</h1>
      <span data-testid="live-legal-chip" className={`rounded-sm border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${MONO}`}
        style={{ borderColor: C.red, color: C.red }}>Live legal? NO · size 0</span>
      <span className={`border px-2 py-0.5 text-[10px] font-semibold ${MONO}`} style={{ borderColor: biasColor, color: biasColor }} title={flow?.bias?.rule ?? undefined}>
        BIAS {bias ?? "—"}
      </span>
      <span className={`border px-2 py-0.5 text-[10px] ${MONO}`} style={{ borderColor: trigColor, color: trigColor }}>
        TRIGGER {trig ? `${nf(trig.px, 2)} ${trig.dir} · ${trig.state}` : "—"}
      </span>
      <div className={`ml-auto flex items-baseline gap-3 ${MONO}`}>
        <span className="text-[22px] font-semibold leading-none" style={{ color: C.text }}>{nf(p?.last, 2)}</span>
        <span className="text-[10px]" style={{ color: C.dim }}>bid {nf(p?.bid, 2)} / ask {nf(p?.ask, 2)}</span>
      </div>
      <div className="flex w-full flex-wrap items-center gap-1.5" data-testid="freshness-chips">
        <FreshChip testId="chip-flow" label="FLOW" ageS={flowAge} intervalS={payload?.flow.interval_s ?? 5} />
        <FreshChip testId="chip-rec" label="REC" ageS={recAge} intervalS={5} />
        <FreshChip testId="chip-nq" label="NQ" ageS={nqAge} intervalS={flow?.nq?.interval_s ?? 60} />
        <FreshChip testId="chip-gex" label="GEX" ageS={src(payload?.gex)} intervalS={payload?.gex.interval_s ?? 900} />
        <FreshChip testId="chip-dw" label="DOUBLEWIDE" ageS={src(payload?.doublewide)} intervalS={payload?.doublewide.interval_s ?? 3600} />
        <FreshChip testId="chip-aaron" label="AARON" ageS={src(payload?.aaron)} intervalS={payload?.aaron.interval_s ?? 3600} />
        <span suppressHydrationWarning className={`ml-auto text-[10px] ${MONO}`} style={{ color: C.dim }}>
          {new Date(nowMs).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour12: false })} CT
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------ tiles
function Tile({ k, v, sub, color, testId }: { k: string; v: React.ReactNode; sub?: React.ReactNode; color?: string; testId?: string }) {
  return (
    <div data-testid={testId} className="border px-2 py-1.5" style={{ borderColor: C.line, background: "#090c11" }}>
      <div className="text-[9px] uppercase tracking-[0.12em]" style={{ color: C.dim }}>{k}</div>
      <div className={`text-[17px] font-semibold leading-tight ${MONO}`} style={{ color: color ?? C.text }}>{v}</div>
      {sub != null && <div className={`text-[10px] ${MONO}`} style={{ color: C.dim }}>{sub}</div>}
    </div>
  );
}

export function ReadoutTiles({ flow }: { flow: FlowOut | null }) {
  const g = flow?.gate_cvd ?? null;
  const gColor = g?.side === "above" ? C.green : g?.side === "below" ? C.red : C.amber;
  const lpm = flow?.lots_per_min;
  const p = flow?.price;
  const vsVwap = p?.last != null && p?.vwap != null ? p.last - p.vwap : null;
  const basis = flow?.basis;
  const tick = basis?.label === "tick-rule";
  return (
    <div className="grid grid-cols-2 gap-1.5" data-testid="readout-tiles">
      <Tile k="CVD" v={nf(flow?.cvd?.value, 0)} sub={flow?.cvd?.since_ct ? `since ${flow?.cvd?.since_ct.slice(11, 16)} CT` : undefined} color={g ? gColor : undefined} testId="tile-cvd" />
      <Tile k="vs gate" v={nf(g?.dist, 0, true)} sub={g ? `${g.side} ${nf(g.level, 0)}${g.last_cross_ct ? ` · x ${g.last_cross_ct}` : ""}` : "no gate"} color={g ? gColor : undefined} testId="tile-gate" />
      <Tile k="Lots/min" v={nf(lpm?.last, 0)} sub={`5m ${nf(lpm?.avg5, 0)} · 30m ${nf(lpm?.avg30, 0)}`} testId="tile-lpm" />
      <Tile k="Px vs VWAP" v={nf(vsVwap, 2, true)} sub={`vwap ${nf(p?.vwap, 2)}`} testId="tile-vwap" />
      <Tile k="Delta basis" v={basis ? (tick ? "TICK-RULE" : "BID/ASK") : "—"} color={tick ? C.amber : undefined}
        sub={basis ? `${nf(basis.bidask_pct, 1)}% classified at bid/ask` : undefined} testId="tile-basis" />
      <Tile k="Session" v={nf(flow?.session?.trades, 0)} sub={`${nf(flow?.session?.lots, 0)} lots · ${flow?.session?.trading_day ?? "—"}`} testId="tile-session" />
      <Tile k="Hi / Lo" v={`${nf(p?.hi, 2)}`} sub={`lo ${nf(p?.lo, 2)}`} />
      <Tile k="Recorder" v={flow?.recorder?.state ?? "—"} color={flow?.recorder?.state === "recording" ? C.green : C.amber}
        sub={`tick ${flow?.recorder?.last_tick_age_s != null ? Math.round(flow?.recorder?.last_tick_age_s) + "s" : "—"} · rc ${flow?.recorder?.reconnects ?? "—"}`} testId="tile-rec" />
    </div>
  );
}

// ------------------------------------------------------------------------------------ gate levels
export function GateLevels({ flow }: { flow: FlowOut | null }) {
  const levels = [...(flow?.levels ?? [])].sort((a, b) => (b.px ?? 0) - (a.px ?? 0));
  const g = flow?.gate_cvd;
  const col = (bias: string | null, status: string | null) =>
    status === "confirmed" ? (bias === "bear" ? C.red : bias === "bull" ? C.green : C.text) : status === "touched" ? C.amber : C.dim;
  return (
    <Panel title="Gate levels" testId="panel-gate-levels" right={<span className={`text-[9px] ${MONO}`} style={{ color: C.dim }}>5m close rule</span>}>
      <table className={`w-full text-[11px] ${MONO}`}>
        <thead>
          <tr className="text-left text-[9px] uppercase" style={{ color: C.dim }}>
            <th className="pb-1 font-normal">Level</th><th className="pb-1 text-right font-normal">Px</th>
            <th className="pb-1 text-right font-normal">Dist</th><th className="pb-1 text-right font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {g && (
            <tr data-testid="gate-row-cvd" className="border-t" style={{ borderColor: C.line }}>
              <td style={{ color: C.text }}>{g.label ?? "CVD gate"}</td>
              <td className="text-right">{nf(g.level, 0)}</td>
              <td className="text-right">{nf(g.dist, 0, true)}</td>
              <td className="text-right font-semibold uppercase" style={{ color: g.side === "above" ? C.green : g.side === "below" ? C.red : C.amber }}>{g.side}</td>
            </tr>
          )}
          {levels.map((l) => (
            <tr key={`${l.name}-${l.px}`} className="border-t" style={{ borderColor: C.line }}>
              <td style={{ color: C.text }}>{l.name}<span className="ml-1 text-[9px]" style={{ color: C.dim }}>{l.dir === "above" ? "▲" : "▼"}</span></td>
              <td className="text-right">{nf(l.px, 2)}</td>
              <td className="text-right" style={{ color: C.dim }}>{nf(l.dist, 2, true)}</td>
              <td className="text-right font-semibold uppercase" style={{ color: col(l.bias, l.status) }}>{l.status}</td>
            </tr>
          ))}
          {levels.length === 0 && !g && (
            <tr><td colSpan={4} className="py-3 text-center text-[10px] uppercase" style={{ color: C.dim }}>no gate levels configured</td></tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

// ------------------------------------------------------------------------------------ legs
export function LegsTable({ flow }: { flow: FlowOut | null }) {
  const legs = [...(flow?.legs ?? [])].reverse().slice(0, 8);
  return (
    <Panel title="Legs (swing)" testId="panel-legs" right={<span className={`text-[9px] ${MONO}`} style={{ color: C.dim }}>newest first</span>}>
      <table className={`w-full text-[11px] ${MONO}`}>
        <thead>
          <tr className="text-[9px] uppercase" style={{ color: C.dim }}>
            <th className="pb-1 text-left font-normal">#</th><th className="pb-1 text-left font-normal">Start</th>
            <th className="pb-1 text-right font-normal">Pts</th><th className="pb-1 text-right font-normal">Delta</th>
            <th className="pb-1 text-right font-normal">Lots</th><th className="pb-1 text-right font-normal">L/min</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((g) => {
            const c = (g.dir === "up") ? C.green : C.red;
            return (
              <tr key={g.n} className="border-t" style={{ borderColor: C.line }}>
                <td style={{ color: c }}>{g.dir === "up" ? "▲" : "▼"}{g.n}{g.open ? "*" : ""}</td>
                <td style={{ color: C.dim }}>{g.t0 != null ? ctHM(g.t0) : "—"}</td>
                <td className="text-right" style={{ color: c }}>{nf(g.pts, 1, true)}</td>
                <td className="text-right" style={{ color: (g.delta ?? 0) >= 0 ? C.green : C.red }}>{nf(g.delta, 0, true)}</td>
                <td className="text-right">{nf(g.vol, 0)}</td>
                <td className="text-right">{nf(g.lpm, 0)}</td>
              </tr>
            );
          })}
          {legs.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-[10px] uppercase" style={{ color: C.dim }}>no confirmed swing yet</td></tr>}
        </tbody>
      </table>
      <p className="mt-1 text-[9px]" style={{ color: C.dim }}>* open leg, reversal not yet confirmed. Delta = signed lots inside the leg.</p>
    </Panel>
  );
}

// ------------------------------------------------------------------------------------ NQ
export function NqPanel({ flow, nowMs }: { flow: FlowOut | null; nowMs: number }) {
  const nq = flow?.nq;
  const rel = nq?.rel;
  const es = flow?.series_1m ?? [];
  const nqs = nq?.series ?? [];
  const esMap = new Map(es.map((b) => [b.t, b.c]));
  const common = nqs.filter((b) => b.t != null && esMap.has(b.t) && b.c != null);
  let spark: React.ReactNode = <div className="py-4 text-center text-[10px] uppercase" style={{ color: C.dim }}>waiting for overlapping ES/NQ bars</div>;
  if (common.length >= 2) {
    const n0 = common[0].c as number, e0 = esMap.get(common[0].t)! as number;
    const a = common.map((b) => ((b.c as number) / n0 - 1) * 100);
    const e = common.map((b) => (((esMap.get(b.t) as number) / e0) - 1) * 100);
    const all = [...a, ...e, 0];
    const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 0.01;
    const W = 300, H = 70;
    const px = (i: number) => (i / (common.length - 1)) * W;
    const py = (v: number) => H - 4 - ((v - lo) / span) * (H - 8);
    const path = (arr: number[]) => arr.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join("");
    spark = (
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" data-testid="nq-spark">
        <line x1={0} x2={W} y1={py(0)} y2={py(0)} stroke={C.faint} strokeDasharray="2 3" />
        <path d={path(e)} fill="none" stroke={C.price} strokeWidth={1.2} />
        <path d={path(a)} fill="none" stroke={C.series} strokeWidth={1.6} />
      </svg>
    );
  }
  const leadColor = rel?.lead === "NQ leading" ? C.green : rel?.lead === "NQ lagging" ? C.red : C.dim;
  const rows: [string, { nq_pct: number | null; es_pct: number | null; rs: number | null } | null | undefined][] = [
    ["30m", rel?.windows?.["30m"]], ["60m", rel?.windows?.["60m"]], ["session", rel?.windows?.session],
  ];
  const gateSide = rel?.gate?.side;
  return (
    <Panel title="NQ relative strength" testId="panel-nq"
      right={<span className={`text-[10px] font-semibold uppercase ${MONO}`} style={{ color: nq?.status === "ok" ? leadColor : C.amber }}>{nq?.status === "ok" ? rel?.lead ?? "—" : `NQ feed ${nq?.status ?? "—"}`}</span>}>
      {spark}
      <div className="mt-1 flex items-center justify-between text-[9px]" style={{ color: C.dim }}>
        <span><span style={{ color: C.series }}>━</span> NQ % <span style={{ color: C.price }}>━</span> ES %</span>
        <span>since window start · {nowMs ? "" : ""}1-min bars</span>
      </div>
      <table className={`mt-1 w-full text-[11px] ${MONO}`}>
        <thead><tr className="text-[9px] uppercase" style={{ color: C.dim }}><th className="text-left font-normal">Window</th><th className="text-right font-normal">NQ %</th><th className="text-right font-normal">ES %</th><th className="text-right font-normal">RS</th></tr></thead>
        <tbody>
          {rows.map(([k, w]) => (
            <tr key={k} className="border-t" style={{ borderColor: C.line }}>
              <td>{k}</td><td className="text-right">{nf(w?.nq_pct, 3, true)}</td><td className="text-right">{nf(w?.es_pct, 3, true)}</td>
              <td className="text-right font-semibold" style={{ color: (w?.rs ?? 0) > 0 ? C.green : (w?.rs ?? 0) < 0 ? C.red : C.dim }}>{nf(w?.rs, 3, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={`mt-1 text-[10px] ${MONO}`} style={{ color: C.dim }}>
        NQ {nf(rel?.last, 2)} · gate {nf(rel?.gate?.level, 0)}{" "}
        <span style={{ color: gateSide === "above" ? C.green : gateSide === "below" ? C.red : C.dim }}>{gateSide ?? "—"}</span>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------------------------ sources
function dist(level: number | null | undefined, price: number | null | undefined) {
  return level != null && price != null ? level - price : null;
}

function SourceShell({ name, env, nowMs, children, file, seedNote, testId }: {
  name: string; env: SourceEnvelope<unknown>; nowMs: number; children: React.ReactNode; file: string; seedNote?: string | null; testId: string;
}) {
  const ageS = ageSeconds(env.as_of_ms, nowMs);
  const level = freshnessLevel(ageS, env.interval_s);
  const asOf = env.as_of_ms != null
    ? new Date(env.as_of_ms).toLocaleString("en-CA", { timeZone: "America/Chicago", hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "")
    : null;
  return (
    <Panel title={name} testId={testId} className="col-span-12 lg:col-span-4"
      right={<FreshChip testId={`${testId}-chip`} label="AS OF" ageS={ageS} intervalS={env.interval_s} />}>
      <StaleBanner level={level} ageS={ageS} asOf={asOf} present={env.present} what={file} />
      {seedNote && <div className="mb-2 text-[9px] uppercase tracking-wide" style={{ color: C.amber }}>{seedNote}</div>}
      {children}
    </Panel>
  );
}

function KV({ k, v, d }: { k: string; v: React.ReactNode; d?: number | null }) {
  return (
    <tr className="border-t" style={{ borderColor: C.line }}>
      <td style={{ color: C.dim }}>{k}</td>
      <td className="text-right" style={{ color: C.text }}>{v}</td>
      <td className="w-16 text-right" style={{ color: C.dim }}>{d != null ? nf(d, 1, true) : ""}</td>
    </tr>
  );
}

export function GexSection({ env, price, nowMs }: { env: SourceEnvelope<GexOut>; price: number | null | undefined; nowMs: number }) {
  const d = env.data;
  return (
    <SourceShell name="GEX" env={env} nowMs={nowMs} file="gex-latest.json" testId="src-gex">
      {d ? (
        <table className={`w-full text-[11px] ${MONO}`}>
          <thead><tr className="text-[9px] uppercase" style={{ color: C.dim }}><th className="text-left font-normal">Level</th><th className="text-right font-normal">Px</th><th className="text-right font-normal">vs last</th></tr></thead>
          <tbody>
            <KV k="Call wall" v={nf(d.call_wall, 0)} d={dist(d.call_wall, price)} />
            <KV k="Gamma flip" v={nf(d.flip, 0)} d={dist(d.flip, price)} />
            <KV k="Pin" v={nf(d.pin, 0)} d={dist(d.pin, price)} />
            <KV k="Max pain" v={nf(d.max_pain, 0)} d={dist(d.max_pain, price)} />
            <KV k="Put wall" v={nf(d.put_wall, 0)} d={dist(d.put_wall, price)} />
            <KV k="Net GEX" v={d.net_gex ?? dash} />
            <KV k="Flip drift" v={d.flip_vel_pts_hr != null ? `${nf(d.flip_vel_pts_hr, 1, true)} pt/h` : dash} />
          </tbody>
        </table>
      ) : <div className="py-4 text-center text-[10px] uppercase" style={{ color: C.dim }}>no GEX data</div>}
      <div className="mt-1 text-[9px]" style={{ color: C.dim }}>{d?.source ?? ""}</div>
    </SourceShell>
  );
}

export function LevelSection({ name, env, price, nowMs, file, testId }: {
  name: string; env: SourceEnvelope<LevelSourceOut>; price: number | null | undefined; nowMs: number; file: string; testId: string;
}) {
  const d = env.data;
  const levels = [...(d?.levels ?? [])].sort((a, b) => (b.px ?? 0) - (a.px ?? 0));
  return (
    <SourceShell name={name} env={env} nowMs={nowMs} file={file} testId={testId} seedNote={env.seed ? "seed copy, producer not wired yet" : null}>
      {d ? (
        <table className={`w-full text-[11px] ${MONO}`}>
          <thead><tr className="text-[9px] uppercase" style={{ color: C.dim }}><th className="text-left font-normal">Level</th><th className="text-right font-normal">Zone</th><th className="text-right font-normal">vs last</th></tr></thead>
          <tbody>
            {levels.map((l) => (
              <KV key={`${l.name}-${l.px}`} k={l.name ?? "level"} v={l.px2 != null ? `${nf(l.px, 0)}–${nf(l.px2, 0)}` : nf(l.px, 0)} d={dist(l.px, price)} />
            ))}
          </tbody>
        </table>
      ) : <div className="py-4 text-center text-[10px] uppercase" style={{ color: C.dim }}>no levels</div>}
      <div className="mt-1 text-[9px]" style={{ color: C.dim }}>{d?.note ?? ""}{d?.source ? ` · ${d.source}` : ""}</div>
    </SourceShell>
  );
}

// ------------------------------------------------------------------------------------ footer
export function GatesFooter({ gates }: { gates: TapePayload["gates"] | undefined }) {
  const col = (s: string) => (s === "pass" ? C.green : s === "fail" ? C.red : s === "warn" ? C.amber : C.dim);
  return (
    <footer data-testid="gates-footer" className="col-span-12 border px-3 py-2" style={{ borderColor: C.line, background: C.panel }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em]" style={{ color: C.dim }}>Hermes gates</span>
        {gates && !gates.found && <span className={`border px-1.5 py-0.5 text-[10px] ${MONO}`} style={{ borderColor: C.amber, color: C.amber }}>gates file missing</span>}
        {gates?.lockout != null && (
          <span className={`border px-1.5 py-0.5 text-[10px] ${MONO}`} style={{ borderColor: gates.lockout ? C.red : C.green, color: gates.lockout ? C.red : C.green }}>lockout {gates.lockout ? "ON" : "off"}</span>
        )}
        {(gates?.gates ?? []).map((g) => (
          <span key={g.name} className={`border px-1.5 py-0.5 text-[10px] ${MONO}`} style={{ borderColor: col(g.status), color: col(g.status) }}>{g.status.toUpperCase()} · {g.name}</span>
        ))}
        <span className="ml-auto text-[9px]" style={{ color: C.dim }}>Descriptive read-only tape. IB read-only. Not a signal.</span>
      </div>
    </footer>
  );
}
