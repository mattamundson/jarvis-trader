"use client";

import type { FlowOut } from "@/lib/tape/serialize";
import { C, ctHM, nf } from "./theme";

const W = 1000, ML = 56, MR = 56;
const A0 = 10, A1 = 250;       // CVD + price pane
const B0 = 270, B1 = 350;      // per-leg delta
const C0 = 372, C1 = 436;      // lots/min
const H = 462;

function scale(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1;
  return (v: number) => r1 - ((v - d0) / span) * (r1 - r0);
}
const nn = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

export function FlowChart({ flow }: { flow: FlowOut | null }) {
  const series = (flow?.series_1m ?? []).filter((b) => nn(b.t) && nn(b.c) && nn(b.cvd));
  if (!flow || series.length < 2) {
    return (
      <div data-testid="flow-chart-empty" className="flex h-[300px] items-center justify-center text-[11px] uppercase tracking-wider" style={{ color: C.dim }}>
        Waiting for recorder ticks. Order-flow chart needs at least two 1-minute bars.
      </div>
    );
  }
  const last = series[series.length - 1];
  const tMax = (last.t as number) + 60;
  const tMin = Math.min(series[0].t as number, tMax - 20 * 60);
  const x = (t: number) => ML + ((t - tMin) / (tMax - tMin)) * (W - ML - MR);

  const cvdVals = series.map((b) => b.cvd as number);
  const gate = flow.gate_cvd;
  const gateLvl = nn(gate?.level) ? gate!.level! : null;
  const dom = [...cvdVals, 0, ...(gateLvl != null ? [gateLvl] : [])];
  const cLo = Math.min(...dom), cHi = Math.max(...dom), cPad = (cHi - cLo) * 0.08 || 1;
  const yC = scale(cLo - cPad, cHi + cPad, A0, A1);
  const px = series.map((b) => b.c as number);
  const pLo = Math.min(...px), pHi = Math.max(...px), pPad = (pHi - pLo) * 0.12 || 0.5;
  const yP = scale(pLo - pPad, pHi + pPad, A0, A1);

  const cvdPath = series.map((b, i) => `${i ? "L" : "M"}${x(b.t as number).toFixed(1)},${yC(b.cvd as number).toFixed(1)}`).join("");
  const pxPath = series.map((b, i) => `${i ? "L" : "M"}${x(b.t as number).toFixed(1)},${yP(b.c as number).toFixed(1)}`).join("");
  const sideColor = gate?.side === "above" ? C.green : gate?.side === "below" ? C.red : C.amber;

  const legs = (flow.legs ?? []).filter((g) => nn(g.t0) && nn(g.t1) && nn(g.delta) && (g.t1 as number) >= tMin);
  const maxD = Math.max(1, ...legs.map((g) => Math.abs(g.delta as number)));
  const zeroB = (B0 + B1) / 2;

  const volByT = new Map(series.map((b) => [b.t as number, b.vol as number]));
  const mins: number[] = [];
  for (let t = Math.ceil(tMin / 60) * 60; t < tMax; t += 60) mins.push(t);
  const maxV = Math.max(1, ...mins.map((t) => volByT.get(t) ?? 0));
  const yV = scale(0, maxV, C0, C1);
  const barW = Math.max(1, ((W - ML - MR) / Math.max(1, mins.length)) * 0.72);

  const ticks: number[] = [];
  const stepMin = (tMax - tMin) / 60 > 180 ? 30 : (tMax - tMin) / 60 > 90 ? 15 : 5;
  for (let t = Math.ceil(tMin / (stepMin * 60)) * stepMin * 60; t <= tMax; t += stepMin * 60) ticks.push(t);

  return (
    <svg data-testid="flow-chart" viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img"
      aria-label="CVD line with gate, price, per-leg delta and lots per minute"
      style={{ background: C.panel, fontFamily: "var(--font-mono, ui-monospace, monospace)" }}>
      {/* vertical time grid */}
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={A0} y2={C1} stroke={C.grid} strokeWidth={1} />
          <text x={x(t)} y={H - 8} fontSize={10} fill={C.dim} textAnchor="middle">{ctHM(t)}</text>
        </g>
      ))}
      {/* pane frames */}
      {[[A0, A1], [B0, B1], [C0, C1]].map(([a, b], i) => <rect key={i} x={ML} y={a} width={W - ML - MR} height={b - a} fill="none" stroke={C.line} />)}

      {/* leg boundaries through the main pane */}
      {legs.map((g) => <line key={`lb${g.n}`} x1={x(g.t0 as number)} x2={x(g.t0 as number)} y1={A0} y2={A1} stroke={C.faint} strokeDasharray="2 4" />)}

      {/* zero + gate */}
      <line x1={ML} x2={W - MR} y1={yC(0)} y2={yC(0)} stroke={C.faint} strokeWidth={0.7} />
      {gateLvl != null && (
        <g data-testid="cvd-gate-rule">
          <line x1={ML} x2={W - MR} y1={yC(gateLvl)} y2={yC(gateLvl)} stroke={C.amber} strokeDasharray="6 4" strokeWidth={1.2} />
          <text x={ML + 6} y={yC(gateLvl) - 4} fontSize={10} fill={C.amber}>{`${gate?.label ?? "GATE"} ${nf(gateLvl, 0)}`}</text>
        </g>
      )}

      <path d={pxPath} fill="none" stroke={C.price} strokeWidth={1.2} />
      <path d={cvdPath} fill="none" stroke={C.series} strokeWidth={1.8} />
      <circle cx={x(last.t as number)} cy={yC(last.cvd as number)} r={3.5} fill={sideColor} />

      {/* axes: CVD left, price right */}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => {
        const v = cLo - cPad + f * (cHi - cLo + 2 * cPad);
        const p = pLo - pPad + f * (pHi - pLo + 2 * pPad);
        return (
          <g key={f}>
            <text x={ML - 6} y={yC(v) + 3} fontSize={10} fill={C.series} textAnchor="end">{nf(v, 0)}</text>
            <text x={W - MR + 6} y={yP(p) + 3} fontSize={10} fill={C.price}>{nf(p, 2)}</text>
          </g>
        );
      })}
      <text x={ML} y={A0 - 1} fontSize={9} fill={C.series}>CVD</text>
      <text x={W - MR} y={A0 - 1} fontSize={9} fill={C.price} textAnchor="end">ES PRICE</text>

      {/* per-leg delta bars */}
      <line x1={ML} x2={W - MR} y1={zeroB} y2={zeroB} stroke={C.faint} strokeWidth={0.7} />
      <text x={ML - 6} y={zeroB + 3} fontSize={10} fill={C.dim} textAnchor="end">0</text>
      <text x={ML} y={B0 - 3} fontSize={9} fill={C.dim}>DELTA PER LEG (lots)</text>
      {legs.map((g) => {
        const d = g.delta as number;
        const x0 = Math.max(ML, x(Math.max(g.t0 as number, tMin)));
        const x1 = x(g.t1 as number);
        const w = Math.max(4, x1 - x0 - 2);
        const h = (Math.abs(d) / maxD) * ((B1 - B0) / 2 - 12);
        const up = d >= 0;
        const col = up ? C.green : C.red;
        return (
          <g key={`lg${g.n}`} data-testid="leg-bar">
            <rect x={x0 + 1} y={up ? zeroB - h : zeroB} width={w} height={Math.max(1, h)} fill={col} fillOpacity={g.open ? 0.28 : 0.7}
              stroke={col} strokeDasharray={g.open ? "3 2" : undefined} />
            <text x={x0 + 1 + w / 2} y={up ? zeroB - h - 3 : zeroB + h + 10} fontSize={9} fill={col} textAnchor="middle">{nf(d, 0, true)}</text>
            <text x={x0 + 1 + w / 2} y={B1 - 2} fontSize={8} fill={C.dim} textAnchor="middle">{`${nf(g.pts as number, 1, true)}p`}</text>
          </g>
        );
      })}

      {/* lots / minute */}
      <text x={ML} y={C0 - 3} fontSize={9} fill={C.dim}>{`LOTS / MIN  (peak ${nf(maxV, 0)})`}</text>
      <text x={ML - 6} y={C0 + 8} fontSize={10} fill={C.dim} textAnchor="end">{nf(maxV, 0)}</text>
      <text x={ML - 6} y={C1} fontSize={10} fill={C.dim} textAnchor="end">0</text>
      {mins.map((t, i) => {
        const v = volByT.get(t) ?? 0;
        const forming = i === mins.length - 1;
        return <rect key={t} x={x(t) - barW / 2} y={yV(v)} width={barW} height={Math.max(0, C1 - yV(v))} fill={forming ? C.faint : "#34404e"} />;
      })}
      {flow.lots_per_min?.avg5 != null && (
        <line x1={ML} x2={W - MR} y1={yV(flow.lots_per_min.avg5)} y2={yV(flow.lots_per_min.avg5)} stroke={C.dim} strokeDasharray="1 3" />
      )}
    </svg>
  );
}
