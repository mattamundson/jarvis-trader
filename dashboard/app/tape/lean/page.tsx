"use client";
import { fetchDashboardApi } from "@/lib/api";
/**
 * Lean Tape screen (screen 1 of the lean dashboard). Read-only readout.
 * Reads only /api/flow/tape (flow-latest.json + gex-latest.json + config/tape-plan.json).
 * Prices, levels and gates only. No dollar amounts, accounts or positions.
 * ?sim=stale shifts the clock 2h forward to preview the STALE states.
 *
 * Freshness/availability (PR1013 secondary surface): the lean screen shares the MAIN
 * gates — tapeEvaluationAllowed (fresh snapshot + an ACTUAL tick + no fetch failure;
 * a future source clock never counts as fresh) and planAvailability for the plan's
 * trigger/invalidation levels (stale/wrong-session/conflicting plans are historical
 * reference, withheld from the chart overlay).
 */
import { useEffect, useState } from "react";
import { normalizeSnapshot } from "@/lib/tapeDerive";
import { normalizePlan, planAvailability } from "@/lib/tapePlan";
import { tapeEvaluationAllowed } from "@/lib/tapeFreshnessContract";

const FLOW_STALE_S = 60;
const GEX_STALE_S = 30 * 60;
const REFRESH_MS = 10_000;

type Bar = { t: number; c: number; h: number; l: number; delta: number | null; cvd: number | null };
type Any = Record<string, any>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const f2 = (v: number | null) => (v === null ? "--" : v.toFixed(2));
const sgn = (v: number | null, d = 0) => (v === null ? "--" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`);
const ct = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hour12: false });
function age(s: number | null) {
  if (s === null) return "unknown age";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function Panel({ title, stale, ageS, children, style }: { title: string; stale?: boolean; ageS?: number | null; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <section style={{ background: "#11151c", border: `1px solid ${stale ? "#7a5b12" : "#1f2632"}`, borderRadius: 8, padding: 12, ...style }}>
      <header style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#8b95a7", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
        <span>{title}</span>
        {ageS !== undefined && (
          <span style={{ color: stale ? "#f5b82e" : "#5d6b80", fontWeight: stale ? 700 : 400 }}>{stale ? `STALE · ${age(ageS ?? null)}` : `age ${age(ageS ?? null)}`}</span>
        )}
      </header>
      {children}
    </section>
  );
}

function Chart({ bars, vwap, levels, stale }: { bars: Bar[]; vwap: number | null; levels: { name: string; px: number; color: string }[]; stale: boolean }) {
  if (!bars.length) return <div style={{ color: "#5d6b80", padding: 40 }}>No 1m bars in snapshot.</div>;
  const W = 960, PH = 300, DH = 80, CH = 80, PAD = 130;
  const pw = W - PAD;
  let lo = Math.min(...bars.map((b) => b.l)), hi = Math.max(...bars.map((b) => b.h));
  if (vwap !== null) { lo = Math.min(lo, vwap); hi = Math.max(hi, vwap); }
  const near = levels.filter((l) => l.px >= lo - 6 && l.px <= hi + 6);
  for (const l of near) { lo = Math.min(lo, l.px); hi = Math.max(hi, l.px); }
  const p = Math.max(0.5, (hi - lo) * 0.05); lo -= p; hi += p;
  const step = pw / bars.length;
  const x = (i: number) => i * step + step / 2;
  const y = (v: number) => 6 + ((hi - v) / (hi - lo)) * (PH - 12);
  const md = Math.max(1, ...bars.map((b) => b.delta === null ? 0 : Math.abs(b.delta)));
  const dz = PH + 8 + DH / 2;
  const cvdKnown = bars.every(b => b.cvd !== null && Number.isFinite(b.cvd));
  const cvals = bars.map(b => b.cvd).filter((v): v is number => v !== null && Number.isFinite(v));
  const cmin = cvals.length ? Math.min(...cvals) : 0, cmax = Math.max(...cvals, cmin + 1);
  const cy = (v: number) => PH + DH + 16 + ((cmax - v) / (cmax - cmin)) * (CH - 8);
  const path = (pts: [number, number][]) => pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("");
  const every = Math.max(1, Math.round(bars.length / 8));
  return (
    <svg viewBox={`0 0 ${W} ${PH + DH + CH + 34}`} style={{ width: "100%", opacity: stale ? 0.45 : 1 }}>
      {near.map((l) => (
        <g key={l.name + l.px}>
          <line x1={0} x2={pw} y1={y(l.px)} y2={y(l.px)} stroke={l.color} strokeDasharray="4 4" strokeWidth={1} />
          <text x={pw + 6} y={y(l.px) + 4} fill={l.color} fontSize={11}>{l.name} {l.px}</text>
        </g>
      ))}
      {vwap !== null && (<><line x1={0} x2={pw} y1={y(vwap)} y2={y(vwap)} stroke="#c084fc" strokeWidth={1.5} /><text x={pw + 6} y={y(vwap) + 4} fill="#c084fc" fontSize={11}>VWAP {f2(vwap)}</text></>)}
      <path d={path(bars.map((b, i) => [x(i), y(b.c)]))} fill="none" stroke="#e5e7eb" strokeWidth={1.6} />
      <text x={pw + 6} y={y(bars[bars.length - 1].c) + 4} fill="#fff" fontSize={12} fontWeight={700}>ES {f2(bars[bars.length - 1].c)}</text>
      <line x1={0} x2={pw} y1={dz} y2={dz} stroke="#2a3342" />
      {bars.map((b, i) => { if (b.delta === null) return null; const h = (Math.abs(b.delta) / md) * (DH / 2 - 2); return <rect key={b.t} x={x(i) - step * 0.35} width={Math.max(1, step * 0.7)} y={b.delta >= 0 ? dz - h : dz} height={Math.max(0.5, h)} fill={b.delta >= 0 ? "#22c55e" : "#ef4444"} />; })}
      <text x={pw + 6} y={dz + 4} fill="#8b95a7" fontSize={11}>Δ 1m{bars.some(b => b.delta === null) ? " · Delta unavailable" : ""}</text>
      {cvdKnown ? <>
        <path d={path(bars.map((b, i) => [x(i), cy(b.cvd!)]))} fill="none" stroke="#38bdf8" strokeWidth={1.5} />
        <text x={pw + 6} y={cy(bars[bars.length - 1].cvd!) + 4} fill="#38bdf8" fontSize={11}>CVD {bars[bars.length - 1].cvd}</text>
      </> : <text x={8} y={PH + DH + 36} fill="#8b95a7" fontSize={11}>CVD unavailable</text>}
      {bars.map((b, i) => (i % every === 0 ? <text key={"t" + b.t} x={x(i)} y={PH + DH + CH + 30} fill="#5d6b80" fontSize={10} textAnchor="middle">{ct(b.t)}</text> : null))}
    </svg>
  );
}

export default function LeanTape() {
  const [d, setD] = useState<Any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [sim, setSim] = useState(0);
  useEffect(() => { if (new URLSearchParams(location.search).get("sim") === "stale") setSim(2 * 3600 * 1000); }, []);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try { const j = await fetchDashboardApi<any>("/api/flow/tape"); if (live) { setD(j); setErr(null); } }
      catch (e) { if (live) setErr("readout unreachable"); }
    };
    load();
    const a = setInterval(load, REFRESH_MS), b = setInterval(() => setNow(Date.now()), 1000);
    return () => { live = false; clearInterval(a); clearInterval(b); };
  }, []);

  const t = (now + sim) / 1000;
  const s: Any = d?.snapshot ?? {};
  // Shared main gates: fresh snapshot (known, non-future as-of) + an ACTUAL tick
  // (lastTickAgeS, never the heartbeat) + no current fetch failure. `err` keeps the last
  // good payload visible but marks it cached-after-failure, so it reads as stale.
  const snap = d ? normalizeSnapshot(d.snapshot) : null;
  const hasSnap = d?.ok === true && snap !== null;
  const serverS = typeof d?.serverEpochMs === "number" && Number.isFinite(d.serverEpochMs) ? d.serverEpochMs / 1000 : null;
  const asOf = num(s.as_of_epoch);
  const flowAge = asOf !== null ? t - asOf : null; // negative (future clock) → gate rejects
  const recTickAge = typeof d?.recorder?.lastTickAgeS === "number" ? d.recorder.lastTickAgeS : null;
  const tickAge = recTickAge !== null && serverS !== null ? recTickAge + Math.max(0, t - serverS) : null;
  const fetchFailed = err !== null;
  const evalAllowed = tapeEvaluationAllowed(hasSnap, flowAge, tickAge, fetchFailed, FLOW_STALE_S);
  const flowStale = !evalAllowed;
  const g: Any | null = d?.gex ?? null;
  const gEpoch = g?.asof_ct ? Date.parse(g.asof_ct) / 1000 : g?.pulled_ct ? Date.parse(g.pulled_ct) / 1000 : NaN;
  const gexAge = Number.isFinite(gEpoch) ? t - gEpoch : null;
  const gexStale = !!err || !g || gexAge === null || gexAge < 0 || gexAge > GEX_STALE_S;
  const price: Any = s.price ?? {};
  const last = num(price.last), vwap = num(price.vwap);
  const bars: Bar[] = (snap?.bars ?? []).slice(-120);
  const rel: Any = s.nq?.rel ?? null;
  // Plan-of-record availability: the SAME gate as the main /tape screen. An unusable plan
  // (stale date, wrong session, source conflict) is historical reference only.
  const plan = normalizePlan(d?.plan);
  const planAvail = planAvailability(plan, {
    todayCt: typeof d?.todayCt === "string" ? d.todayCt : null,
    globexTradingDate: typeof d?.globexTradingDate === "string" ? d.globexTradingDate : null,
    recorderSessionTradingDay: typeof d?.recorder?.sessionTradingDay === "string" ? d.recorder.sessionTradingDay : null,
    recorderLevelsSource: typeof d?.recorder?.levelsSource === "string" ? d.recorder.levelsSource : null,
  });
  const planUsable = !!d && evalAllowed && planAvail.usable;
  const recLevels: Any[] = Array.isArray(s.levels) ? s.levels : [];
  const pick = (re: RegExp) => recLevels.find((l) => re.test(String(l.name)))?.px ?? null;

  const rows: { name: string; px: number | null; src: string; color: string; stale?: boolean; staleLabel?: string }[] = [
    { name: "Gamma flip", px: num(g?.flip), src: "ZeroGEX", color: "#f59e0b", stale: gexStale },
    { name: "Call wall", px: num(g?.call_wall), src: "ZeroGEX", color: "#22c55e", stale: gexStale },
    { name: "Put wall", px: num(g?.put_wall), src: "ZeroGEX", color: "#ef4444", stale: gexStale },
    { name: "Max pain", px: num(g?.max_pain), src: "ZeroGEX", color: "#a3a3a3", stale: gexStale },
    { name: "Overnight high", px: num(pick(/overnight high|onh/i)), src: "recorder", color: "#94a3b8" },
    { name: "Overnight low", px: num(pick(/overnight low|onl/i)), src: "recorder", color: "#94a3b8" },
    { name: "Long trigger", px: num(plan?.long?.trigger), src: "tape-plan", color: "#4ade80", stale: !planUsable, staleLabel: " (plan unavailable)" },
    { name: "Long invalidation", px: num(plan?.long?.stop), src: "tape-plan", color: "#f87171", stale: !planUsable, staleLabel: " (plan unavailable)" },
    { name: "Short trigger", px: num(plan?.short?.trigger), src: "tape-plan", color: "#fb7185", stale: !planUsable, staleLabel: " (plan unavailable)" },
    { name: "Short invalidation", px: num(plan?.short?.stop), src: "tape-plan", color: "#f87171", stale: !planUsable, staleLabel: " (plan unavailable)" },
  ];
  const chartLevels = rows.filter((r) => r.px !== null && !r.stale).map((r) => ({ name: r.name, px: r.px as number, color: r.color }));
  const w30 = rel?.windows?.["30m"], w60 = rel?.windows?.["60m"];

  return (
    <main style={{ minHeight: "100vh", background: "#0a0d12", color: "#e5e7eb", fontFamily: "ui-sans-serif, system-ui", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 18, margin: 0, color: "#8b95a7" }}>ES TAPE</h1>
        <span style={{ fontSize: 34, fontWeight: 700, color: flowStale ? "#6b7280" : "#fff" }}>{f2(last)}</span>
        <span style={{ color: last !== null && vwap !== null && last >= vwap ? "#22c55e" : "#ef4444" }}>vs VWAP {f2(vwap)} ({last !== null && vwap !== null ? sgn(last - vwap, 2) : "--"})</span>
        <span style={{ color: "#38bdf8" }}>CVD {sgn(num(s.cvd?.value))}</span>
        <span style={{ color: "#5d6b80", fontSize: 12 }}>as of {s.as_of_ct ?? "--"}</span>
        <span style={{ marginLeft: "auto", fontWeight: 800, color: "#ef4444" }}>LIVE LEGAL? NO · SIZE 0</span>
      </div>
      {err && <div style={{ color: "#f5b82e", marginBottom: 8 }}>{err}</div>}
      {sim > 0 && <div style={{ color: "#f5b82e", marginBottom: 8 }}>Simulation: clock +2h to preview STALE</div>}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,3fr) minmax(260px,1fr)", gap: 12 }}>
        <Panel title="Order flow · price vs VWAP · 1m delta · CVD" stale={flowStale} ageS={flowAge}>
          {!d?.ok && <div style={{ color: "#f5b82e" }}>STALE: {d?.error ?? "no snapshot"}</div>}
          <Chart bars={bars} vwap={vwap} levels={chartLevels} stale={flowStale} />
        </Panel>
        <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
          <Panel title="NQ relative strength" stale={flowStale || !rel} ageS={flowAge}>
            {rel ? (
              <div style={{ fontSize: 14, lineHeight: 1.7 }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{rel.lead ?? "--"}</div>
                <div>NQ {f2(num(rel.last))}</div>
                <div>30m RS {sgn(num(w30?.rs), 3)} (NQ {sgn(num(w30?.nq_pct), 3)}% / ES {sgn(num(w30?.es_pct), 3)}%)</div>
                <div>60m RS {sgn(num(w60?.rs), 3)}</div>
                {rel.gate && <div style={{ color: "#8b95a7" }}>NQ gate {rel.gate.side} {rel.gate.level}</div>}
              </div>
            ) : <div style={{ color: "#f5b82e" }}>STALE: NQ not in snapshot</div>}
          </Panel>
          <Panel title="Levels" stale={gexStale} ageS={gexAge}>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} style={{ borderTop: "1px solid #1a202a" }}>
                    <td style={{ padding: "3px 0", color: r.color }}>{r.name}</td>
                    <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: r.stale ? "#6b7280" : "#e5e7eb" }}>{r.px === null ? "not in feed" : r.px}{r.stale && r.px !== null ? (r.staleLabel ?? " (stale)") : ""}</td>
                    <td style={{ textAlign: "right", color: "#5d6b80", fontSize: 11 }}>{r.src}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ color: "#5d6b80", fontSize: 11, marginTop: 6 }}>Gamma ~15–20 min delayed. Plan date {plan?.date ?? "--"}{!planUsable ? ` · PLAN UNAVAILABLE FOR TRIGGERS: ${!evalAllowed ? "fresh tick/snapshot evidence unavailable" : planAvail.reason}` : ""}{d?.planError ? ` · ${d.planError}` : ""}{plan?.long?.targets?.length ? ` · long targets ${plan.long.targets.join(" / ")}` : ""}</div>
          </Panel>
        </div>
        <Panel title="Footprint" style={{ gridColumn: "1 / -1", minHeight: 120 }}>
          <div style={{ color: "#5d6b80", textAlign: "center", paddingTop: 30 }}>Footprint chart: reserved, to be built later.</div>
        </Panel>
      </div>
    </main>
  );
}
