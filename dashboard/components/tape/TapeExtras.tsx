"use client";
// /tape extras panels (items 2-6). Read-only display; no order buttons.
import { useEffect, useState } from "react";
import { ChartOrTable, FootprintChart, ProfileChart, chartLevels } from "./TapeCharts";

const box = "mb-2 rounded border border-zinc-800 bg-zinc-950 p-2";
const ago = (s: number | null | undefined) => (s == null ? "?" : s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`);
const ct = (t: number) => new Date(t * 1000).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" });

export function SourceTag({ s, age }: { s?: string | null; age?: number | null }) {
  return <span data-testid="panel-source" className="ml-2 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-normal text-zinc-300">source: {s ?? "unknown"}{age != null ? ` · ${ago(age)} old` : ""}{age != null && age > 600 && <b className="ml-1 text-red-400">STALE</b>}</span>;
}

function H({ t, s, age, id }: { t: string; s?: string | null; age?: number | null; id: string }) {
  return <div data-testid={id} className="mb-1 text-[11px] font-bold uppercase tracking-wide text-zinc-400">{t}<SourceTag s={s} age={age} /></div>;
}

function IbLight({ ib }: { ib: any }) {
  const c = ib?.light === "green" ? "bg-emerald-500" : ib?.light === "amber" ? "bg-amber-400" : "bg-red-600";
  return (
    <div className={box}>
      <H id="ib-status-panel" t="IB paper status" s="local read-only checks" />
      <div className="flex flex-wrap items-center gap-3">
        <span className={`inline-block h-3 w-3 rounded-full ${c}`} data-testid="ib-light" title={ib?.light} />
        {(ib?.checks ?? []).map((k: any) => (
          <span key={k.name} className={k.ok === true ? "text-emerald-300" : k.ok === false ? "text-red-300" : "text-amber-300"}>
            {k.ok === true ? "✔" : k.ok === false ? "✖" : "?"} {k.name}{k.value != null ? `: ${k.value}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function Proof({ p, src }: { p: any; src: any }) {
  if (!p?.ok) return <div className={box}><H id="proof-panel" t="Proof record" s={src?.source} />{p?.error ?? "unavailable"}</div>;
  return (
    <div className={box}>
      <H id="proof-panel" t={`Proof record: ${p.counted} of ${p.goal} counted · avg R ${p.avg_R >= 0 ? "+" : ""}${p.avg_R} · total ${p.total_R} · W${p.wins}/L${p.losses}`} s={p.source} age={p.fileAgeS} />
      <div className="max-h-56 overflow-auto">
        <table className="w-full text-[11px]">
          <thead className="text-zinc-500"><tr>{["date", "setup", "side", "trigger", "entry", "stop", "target", "exit", "why", "R", "status", "counted"].map((h) => <th key={h} className="px-1 text-left">{h}</th>)}</tr></thead>
          <tbody>
            {p.setups.map((r: any, i: number) => (
              <tr key={i} className="border-t border-zinc-900">
                <td className="px-1">{r.date}</td><td className="px-1">{r.setup}</td><td className="px-1">{r.side}</td><td className="px-1">{r.trigger}</td>
                <td className="px-1">{r.entry}</td><td className="px-1">{r.stop}</td><td className="px-1">{r.target}</td><td className="px-1">{r.exit}</td><td className="px-1">{r.exit_reason}</td>
                <td className={`px-1 ${Number(r.R) > 0 ? "text-emerald-300" : Number(r.R) < 0 ? "text-red-300" : ""}`}>{r.R}</td><td className="px-1">{r.status}</td><td className="px-1">{r.counted ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PlanCard({ p, src }: { p: any; src: any }) {
  if (!p?.ok) return <div className={box}><H id="plan-card" t="Plan card" s={src?.source} />{p?.error ?? "unavailable"}</div>;
  return (
    <div className={box}>
      <H id="plan-card" t={`Plan card ${p.date ?? ""}${p.planIsToday ? "" : " (NOT today's plan)"}${p.pastVoid ? " · new legs void after 2:00 PM CT" : ""}`} s={src?.source} age={src?.ageS} />
      <div className="grid gap-2 sm:grid-cols-2">
        {p.legs.map((l: any) => {
          const lit = l.state === "TRIGGERED" ? "border-emerald-500 bg-emerald-950" : l.state === "TARGET" ? "border-sky-500 bg-sky-950" : l.state === "STOPPED" ? "border-red-600 bg-red-950" : l.state.startsWith("VOID") ? "border-zinc-700 opacity-60" : "border-zinc-700";
          return (
            <div key={l.side} data-testid={`plan-leg-${l.side}`} className={`rounded border p-2 ${lit}`}>
              <div className="font-bold">{l.side.toUpperCase()} · {l.state}{l.triggeredAt ? ` @ ${ct(l.triggeredAt)} CT` : ""}</div>
              <div>trigger {l.trigger} · stop {l.stop} · targets {l.targets.join(", ")} · dist {l.distance}</div>
              <ul>{l.gates.map((g: any) => <li key={g.name} className={g.ok ? "text-emerald-300" : "text-zinc-500"}>{g.ok ? "●" : "○"} {g.name}{g.value != null ? ` (${g.value})` : ""}</li>)}</ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Footprint({ f }: { f: any }) {
  if (!f?.ok) return <div className={box}><H id="footprint-panel" t="Footprint 5m" s={f?.source} />{f?.error ?? "unavailable"}</div>;
  const bars = f.bars.slice(-8);
  const maxV = Math.max(1, ...bars.flatMap((b: any) => b.levels.map((l: any) => Math.max(l.bid, l.ask))));
  return (
    <div className={box}>
      <H id="footprint-panel" t={`Footprint 5m (bid x ask per price, delta per bar) · ${f.file}${f.isToday ? "" : " (not today)"}`} s={f.source} age={f.fileAgeS} />
      <div className="flex gap-1 overflow-x-auto">
        {bars.map((b: any) => (
          <div key={b.t} className="min-w-[110px] text-[10px]">
            <div className="text-center text-zinc-400">{ct(b.t)}</div>
            <div className="max-h-72 overflow-y-auto">
              {b.levels.map((l: any) => (
                <div key={l.px} className="flex justify-between gap-1 px-0.5" style={{ background: `rgba(${l.delta >= 0 ? "16,185,129" : "239,68,68"},${Math.min(0.6, Math.max(l.bid, l.ask) / maxV)})` }}>
                  <span className="text-red-200">{l.bid}</span><span className="text-zinc-400">{l.px}</span><span className="text-emerald-200">{l.ask}</span>
                </div>
              ))}
            </div>
            <div className={`text-center font-bold ${b.delta >= 0 ? "text-emerald-300" : "text-red-300"}`}>Δ {b.delta}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Profile({ p }: { p: any }) {
  if (!p?.ok) return <div className={box}><H id="profile-panel" t="Composite profile" s={p?.source} />{p?.error ?? "unavailable"}</div>;
  const maxV = Math.max(1, ...p.rows.map((r: any) => r.vol)); const maxT = Math.max(1, ...p.rows.map((r: any) => r.tpo));
  return (
    <div className={box}>
      <H id="profile-panel" t={`Composite volume / TPO profile · ${p.days.length} days (${p.days.map((d: string) => d.slice(5, 13)).join(", ")}) · POC ${p.poc} · VAH ${p.vah} · VAL ${p.val}`} s={p.source} />
      <div className="max-h-80 overflow-y-auto text-[10px]">
        {p.rows.map((r: any) => (
          <div key={r.px} className={`flex items-center gap-1 ${r.px === p.poc ? "text-amber-300" : r.px <= p.vah && r.px >= p.val ? "text-zinc-200" : "text-zinc-500"}`}>
            <span className="w-12 text-right">{r.px}</span>
            <span className="inline-block h-2 bg-sky-600" style={{ width: `${(r.vol / maxV) * 220}px` }} />
            <span className="inline-block h-2 bg-violet-600" style={{ width: `${(r.tpo / maxT) * 80}px` }} />
            <span>{r.vol} · {r.tpo} TPO</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TapeExtras() {
  const [d, setD] = useState<any>(null); const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    const go = async () => { try { const r = await fetch("/api/tape/extras", { cache: "no-store" }); const j = await r.json(); if (on) { setD(j); setErr(null); } } catch (e) { if (on) setErr(String(e)); } };
    go(); const id = setInterval(go, 15000); return () => { on = false; clearInterval(id); };
  }, []);
  if (!d) return <div className={box} data-testid="tape-extras">Loading extras…{err ? ` (${err})` : ""}</div>;
  return (
    <section data-testid="tape-extras">
      {d.snapshotMode && <div data-testid="snapshot-mode" className="mb-2 rounded border border-amber-600 bg-amber-950 px-2 py-1 text-amber-200">Snapshot mode: last published snapshot{d.publishedAt ? ` from ${new Date(d.publishedAt).toLocaleString("en-US", { timeZone: "America/Chicago" })} CT` : ""}. Read-only.</div>}
      {d.error && <div className={box}>{d.error}</div>}
      <div data-testid="sources-panel" className={`${box} text-[11px]`}>
        <b className="text-zinc-400">SOURCES</b>{" "}
        {d.sources && Object.entries(d.sources).filter(([k]) => k !== "labels").map(([k, v]: any) => <span key={k} className="mr-3">{k}: <b>{v?.source ?? "unknown"}</b>{v?.ageS != null ? ` (${ago(v.ageS)})` : ""}</span>)}
        <span className="text-zinc-500">· labels: {d.sources?.labels ? Object.values(d.sources.labels).join(" / ") : ""}</span>
      </div>
      <IbLight ib={d.ib} />
      <PlanCard p={d.plan} src={d.sources?.plan ? { ...d.sources.plan, ageS: d.sources.tape?.ageS } : null} />
      <Proof p={d.proof} src={d.sources?.proof} />
      <ChartOrTable id="footprint" chart={<div className="mb-2"><FootprintChart f={d.footprintWide ?? d.footprint} vwap={d.chart?.vwap} last={d.chart?.last} levels={chartLevels(d.chart)} profile={d.profile} /></div>} table={<Footprint f={d.footprint} />} />
      <ChartOrTable id="profile" chart={<div className="mb-2"><ProfileChart p={d.profile} last={d.chart?.last} vwap={d.chart?.vwap} /></div>} table={<Profile p={d.profile} />} />
    </section>
  );
}
