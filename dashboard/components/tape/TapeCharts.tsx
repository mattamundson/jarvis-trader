"use client";
// /tape chart views (addition only): canvas footprint heatmap + composite
// volume profile. The original table views stay available via the toggle.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

const TICK = 0.25;
const FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
const C = {
  bg: "#0a0d12", grid: "#151b24", text: "#cbd5e1", dim: "#64748b", axisBg: "#0f141b",
  bid: [239, 68, 68], ask: [16, 185, 129], poc: "#facc15", vwap: "#e879f9", price: "#38bdf8",
  trigger: "#f59e0b", stop: "#ef4444", target: "#22d3ee", level: "#475569",
};
const rgba = (c: number[], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const ct = (t: number) => new Date(t * 1000).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" });
const fmtV = (v: number) => (v >= 10000 ? `${(v / 1000).toFixed(0)}k` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`);
const r4 = (p: number) => Math.round(p / TICK) * TICK;

export type ChartLevel = { name: string; px: number; kind?: string };

function useCanvas(draw: (g: CanvasRenderingContext2D) => void, w: number, h: number, deps: any[]) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    cv.style.width = `${w}px`; cv.style.height = `${h}px`;
    const g = cv.getContext("2d"); if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.textBaseline = "middle";
    draw(g);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [w, h, ...deps]);
  return ref;
}

function levelColor(l: ChartLevel) {
  const n = l.name.toLowerCase();
  if (l.kind === "trigger" || n.includes("trigger")) return C.trigger;
  if (l.kind === "invalid" || n.includes("stop")) return C.stop;
  if (l.kind === "target" || /\bt\d|target/.test(n)) return C.target;
  return C.level;
}

/** Toggle wrapper: chart is default, original table one click away. */
export function ChartOrTable({ id, chart, table }: { id: string; chart: ReactNode; table: ReactNode }) {
  const [mode, setMode] = useState<"chart" | "table">("chart");
  useEffect(() => { const v = localStorage.getItem(`tape-view-${id}`); if (v === "table" || v === "chart") setMode(v); }, [id]);
  const set = (m: "chart" | "table") => { setMode(m); localStorage.setItem(`tape-view-${id}`, m); };
  return (
    <div data-testid={`${id}-view`}>
      <div className="mb-1 flex justify-end gap-1 text-[10px]">
        {(["chart", "table"] as const).map((m) => (
          <button key={m} data-testid={`${id}-toggle-${m}`} onClick={() => set(m)}
            className={`rounded px-2 py-0.5 ${mode === m ? "bg-sky-700 text-white" : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"}`}>{m}</button>
        ))}
      </div>
      {mode === "chart" ? chart : table}
    </div>
  );
}

function Hdr({ id, t, src, age }: { id: string; t: string; src?: string | null; age?: number | null }) {
  return (
    <div data-testid={id} className="mb-1 flex flex-wrap items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-zinc-400">
      {t}
      <span data-testid="panel-source" className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-normal normal-case text-zinc-300">
        source: {src ?? "unknown"}{age != null ? ` · ${age < 90 ? `${age}s` : `${Math.round(age / 60)}m`} old` : ""}{age != null && age > 600 && <b className="ml-1 text-red-400">STALE</b>}
      </span>
    </div>
  );
}

export function FootprintChart({ f, vwap, last, levels, profile }: { f: any; vwap?: number | null; last?: number | null; levels: ChartLevel[]; profile?: any }) {
  const [zoom, setZoom] = useState(1);
  const [imb, setImb] = useState(3);
  const scroller = useRef<HTMLDivElement>(null);
  const bars: any[] = f?.ok ? f.bars : [];
  const colW = Math.round(96 * zoom), rowH = Math.max(9, Math.round(14 * zoom)), TOP = 22, DELTA_H = 64, AXIS = 150, PROF = 70;
  const fsz = Math.max(8, Math.min(13, Math.round(10 * zoom)));

  const geo = useMemo(() => {
    if (!bars.length) return null;
    let hi = Math.max(...bars.map((b) => b.h)), lo = Math.min(...bars.map((b) => b.l));
    for (const p of [vwap, last]) if (p != null && Math.abs(p - (hi + lo) / 2) < 40) { hi = Math.max(hi, p); lo = Math.min(lo, p); }
    for (const l of levels) if (l.px <= hi + 6 && l.px >= lo - 6) { hi = Math.max(hi, l.px); lo = Math.min(lo, l.px); }
    hi = r4(hi + 1); lo = r4(lo - 1);
    return { hi, lo, rows: Math.round((hi - lo) / TICK) + 1 };
  }, [bars, vwap, last, levels]);

  const W = bars.length * colW + PROF + AXIS;
  const H = geo ? TOP + geo.rows * rowH + DELTA_H + 6 : 120;
  const y = (px: number) => TOP + ((geo!.hi - px) / TICK) * rowH;

  const ref = useCanvas((g) => {
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    if (!geo) return;
    const bodyH = geo.rows * rowH;
    // grid rows
    for (let i = 0; i < geo.rows; i++) { const px = geo.hi - i * TICK; if (Number.isInteger(px)) { g.fillStyle = C.grid; g.fillRect(0, TOP + i * rowH, bars.length * colW, 1); } }
    let maxV = 1; for (const b of bars) for (const l of b.levels) maxV = Math.max(maxV, l.bid, l.ask);
    const maxD = Math.max(1, ...bars.map((b) => Math.abs(b.delta)));
    g.font = `${fsz}px ${FONT}`;
    bars.forEach((b, bi) => {
      const x0 = bi * colW, half = (colW - 8) / 2;
      const map = new Map<number, any>(b.levels.map((l: any) => [l.px, l]));
      let poc: any = null; for (const l of b.levels) if (!poc || l.bid + l.ask > poc.bid + poc.ask) poc = l;
      // candle wick/body strip
      const up = b.c >= b.o; g.fillStyle = up ? rgba(C.ask, 0.9) : rgba(C.bid, 0.9);
      g.fillRect(x0 + 2, y(b.h), 1, y(b.l) - y(b.h) + rowH);
      g.fillRect(x0 + 1, y(Math.max(b.o, b.c)), 3, Math.abs(y(b.o) - y(b.c)) + rowH);
      for (const l of b.levels) {
        const yy = y(l.px), xb = x0 + 6, xa = xb + half;
        g.fillStyle = rgba(C.bid, 0.08 + 0.75 * Math.pow(l.bid / maxV, 0.6)); g.fillRect(xb, yy + 0.5, half - 1, rowH - 1);
        g.fillStyle = rgba(C.ask, 0.08 + 0.75 * Math.pow(l.ask / maxV, 0.6)); g.fillRect(xa, yy + 0.5, half - 1, rowH - 1);
        // diagonal imbalance: ask@px vs bid@px-tick, bid@px vs ask@px+tick
        const below = map.get(r4(l.px - TICK)), above = map.get(r4(l.px + TICK));
        const askImb = l.ask >= 5 && l.ask >= imb * Math.max(1, below?.bid ?? 0);
        const bidImb = l.bid >= 5 && l.bid >= imb * Math.max(1, above?.ask ?? 0);
        if (rowH >= 10) {
          g.textAlign = "right"; g.fillStyle = bidImb ? "#fff" : "#fecaca"; g.font = `${bidImb ? "bold " : ""}${fsz}px ${FONT}`; g.fillText(fmtV(l.bid), xb + half - 4, yy + rowH / 2 + 0.5);
          g.textAlign = "left"; g.fillStyle = askImb ? "#fff" : "#bbf7d0"; g.font = `${askImb ? "bold " : ""}${fsz}px ${FONT}`; g.fillText(fmtV(l.ask), xa + 3, yy + rowH / 2 + 0.5);
        }
        if (bidImb) { g.strokeStyle = "#f87171"; g.lineWidth = 1.5; g.strokeRect(xb + 0.5, yy + 1, half - 2, rowH - 2); }
        if (askImb) { g.strokeStyle = "#34d399"; g.lineWidth = 1.5; g.strokeRect(xa + 0.5, yy + 1, half - 2, rowH - 2); }
      }
      if (poc) { g.strokeStyle = C.poc; g.lineWidth = 2; g.strokeRect(x0 + 5, y(poc.px) - 0.5, colW - 10, rowH + 1); }
      // time label
      g.font = `${fsz}px ${FONT}`; g.textAlign = "center"; g.fillStyle = C.dim; g.fillText(ct(b.t), x0 + colW / 2, TOP / 2);
      // delta histogram
      const dy0 = TOP + bodyH + 6, mid = dy0 + DELTA_H / 2, bh = (Math.abs(b.delta) / maxD) * (DELTA_H / 2 - 10);
      g.fillStyle = b.delta >= 0 ? rgba(C.ask, 0.85) : rgba(C.bid, 0.85);
      g.fillRect(x0 + colW * 0.2, b.delta >= 0 ? mid - bh : mid, colW * 0.6, bh);
      g.fillStyle = b.delta >= 0 ? "#6ee7b7" : "#fca5a5"; g.font = `bold ${fsz}px ${FONT}`;
      g.fillText(`${b.delta >= 0 ? "+" : ""}${b.delta}`, x0 + colW / 2, b.delta >= 0 ? mid + 8 : mid - 8);
      g.fillStyle = C.grid; g.fillRect(x0 + colW - 1, TOP, 1, bodyH + DELTA_H);
    });
    g.fillStyle = "#334155"; g.fillRect(0, TOP + bodyH + 6 + DELTA_H / 2, bars.length * colW, 1);
    g.fillStyle = C.dim; g.textAlign = "left"; g.font = `9px ${FONT}`; g.fillText("Δ delta", 4, TOP + bodyH + 12);
    // aligned composite mini-profile
    const px0 = bars.length * colW;
    g.fillStyle = C.axisBg; g.fillRect(px0, 0, PROF + AXIS, H);
    if (profile?.ok) {
      const inR = profile.rows.filter((r: any) => r.px <= geo.hi && r.px + (profile.bucket ?? 1) > geo.lo);
      const mv = Math.max(1, ...inR.map((r: any) => r.vol));
      for (const r of inR) {
        const yt = y(r.px + (profile.bucket ?? 1) - TICK), hh = ((profile.bucket ?? 1) / TICK) * rowH - 1, w = (r.vol / mv) * (PROF - 8);
        const inVA = r.px <= profile.vah && r.px >= profile.val;
        g.fillStyle = r.px === profile.poc ? C.poc : inVA ? "rgba(56,189,248,0.55)" : "rgba(100,116,139,0.45)";
        g.fillRect(px0 + 4, Math.max(TOP, yt), w, hh);
      }
      g.fillStyle = C.dim; g.font = `9px ${FONT}`; g.textAlign = "left"; g.fillText("composite", px0 + 4, TOP / 2);
    }
    // overlays
    const ax = px0 + PROF;
    const hline = (px: number, color: string, label: string, dash: number[], bold = false) => {
      if (px > geo.hi || px < geo.lo) return;
      const yy = y(px) + rowH / 2;
      g.save(); g.strokeStyle = color; g.lineWidth = bold ? 1.6 : 1; g.setLineDash(dash); g.globalAlpha = bold ? 1 : 0.8;
      g.beginPath(); g.moveTo(0, yy); g.lineTo(ax, yy); g.stroke(); g.restore();
      g.fillStyle = color; g.fillRect(ax, yy - 7, AXIS, 14);
      g.fillStyle = "#0b0f14"; g.font = `bold 10px ${FONT}`; g.textAlign = "left";
      g.fillText(`${px.toFixed(2)} ${label}`.slice(0, 24), ax + 3, yy);
    };
    // price ladder
    g.font = `10px ${FONT}`; g.textAlign = "left";
    for (let i = 0; i < geo.rows; i++) { const px = geo.hi - i * TICK; if (Number.isInteger(px) && (rowH >= 12 || px % 2 === 0)) { g.fillStyle = C.dim; g.fillText(px.toFixed(2), ax + 3, TOP + i * rowH + rowH / 2); } }
    for (const l of levels) hline(l.px, levelColor(l), l.name, l.kind === "level" ? [2, 4] : [6, 3]);
    if (vwap != null) hline(r4(vwap), C.vwap, "VWAP", [8, 3], true);
    if (last != null) hline(r4(last), C.price, "LAST", [], true);
  }, W, H, [bars, geo, zoom, imb, vwap, last, levels, profile]);

  // wheel zoom (non-passive) + start scrolled to the latest bar / price
  useEffect(() => {
    const el = scroller.current; if (!el) return;
    const fn = (e: WheelEvent) => { if (e.shiftKey) return; e.preventDefault(); setZoom((z) => Math.min(2.2, Math.max(0.55, z * (e.deltaY < 0 ? 1.1 : 0.9)))); };
    el.addEventListener("wheel", fn, { passive: false }); return () => el.removeEventListener("wheel", fn);
  }, []);
  const didScroll = useRef(false);
  useEffect(() => {
    const el = scroller.current; if (!el || !geo || didScroll.current) return;
    el.scrollLeft = el.scrollWidth;
    if (last != null) el.scrollTop = Math.max(0, y(r4(last)) - el.clientHeight / 2);
    didScroll.current = true;
  });

  if (!f?.ok) return <div className="rounded border border-zinc-800 bg-[#0a0d12] p-2"><Hdr id="footprint-chart" t="Footprint 5m" src={f?.source} />{f?.error ?? "unavailable"}</div>;
  return (
    <div className="rounded border border-zinc-800 bg-[#0a0d12] p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Hdr id="footprint-chart" t={`Footprint 5m · bid × ask · ${bars.length} bars · ${f.file}${f.isToday ? "" : " (not today)"}`} src={f.source} age={f.fileAgeS} />
        <div className="flex items-center gap-2 text-[10px] text-zinc-400">
          <span>imbalance ≥</span>
          {[2, 3, 4].map((v) => <button key={v} onClick={() => setImb(v)} className={`rounded px-1.5 ${imb === v ? "bg-zinc-700 text-white" : "bg-zinc-900"}`}>{v * 100}%</button>)}
          <button onClick={() => setZoom((z) => Math.max(0.55, z * 0.85))} className="rounded bg-zinc-900 px-1.5">−</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((z) => Math.min(2.2, z * 1.15))} className="rounded bg-zinc-900 px-1.5">+</button>
        </div>
      </div>
      <div ref={scroller} data-testid="footprint-canvas-wrap" className="max-h-[620px] overflow-auto rounded border border-zinc-900">
        <canvas ref={ref} data-testid="footprint-canvas" />
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-[10px] text-zinc-500">
        <span><i className="mr-1 inline-block h-2 w-3 align-middle" style={{ background: C.poc }} />bar POC</span>
        <span><i className="mr-1 inline-block h-2 w-3 border border-emerald-400 align-middle" />ask imbalance</span>
        <span><i className="mr-1 inline-block h-2 w-3 border border-red-400 align-middle" />bid imbalance</span>
        <span style={{ color: C.vwap }}>— VWAP</span><span style={{ color: C.price }}>— last</span>
        <span style={{ color: C.trigger }}>-- trigger</span><span style={{ color: C.stop }}>-- stop</span><span style={{ color: C.target }}>-- target</span>
        <span>wheel = zoom · shift+wheel / drag bar = scroll</span>
      </div>
    </div>
  );
}

export function ProfileChart({ p, last, vwap }: { p: any; last?: number | null; vwap?: number | null }) {
  const scroller = useRef<HTMLDivElement>(null);
  const rows: any[] = p?.ok ? p.rows : [];
  const bucket = p?.bucket ?? 1, rowH = 7, TOP = 8, W = 640, LBL = 64, BARW = 470;
  const H = TOP * 2 + rows.length * rowH;
  const hi = rows[0]?.px ?? 0;
  const y = (px: number) => TOP + ((hi - px) / bucket) * rowH;
  const ref = useCanvas((g) => {
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    if (!rows.length) return;
    const mv = Math.max(1, ...rows.map((r) => r.vol)), mt = Math.max(1, ...rows.map((r) => r.tpo));
    // value area band
    g.fillStyle = "rgba(56,189,248,0.07)"; g.fillRect(LBL, y(p.vah), W - LBL, y(p.val) - y(p.vah) + rowH);
    g.font = `9px ${FONT}`; g.textAlign = "right";
    for (const r of rows) {
      const yy = y(r.px), inVA = r.px <= p.vah && r.px >= p.val;
      g.fillStyle = r.px === p.poc ? C.poc : inVA ? "rgba(56,189,248,0.8)" : "rgba(100,116,139,0.55)";
      g.fillRect(LBL + 4, yy + 0.5, (r.vol / mv) * BARW, rowH - 1);
      g.fillStyle = "rgba(167,139,250,0.55)"; g.fillRect(W - 4 - (r.tpo / mt) * 90, yy + 2, (r.tpo / mt) * 90, rowH - 4);
      if (r.px % 5 === 0) { g.fillStyle = C.dim; g.fillText(r.px.toFixed(0), LBL - 4, yy + rowH / 2); }
    }
    const line = (px: number, color: string, label: string, w = 1, dash: number[] = []) => {
      const yy = y(px) + rowH / 2; g.save(); g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash);
      g.beginPath(); g.moveTo(LBL, yy); g.lineTo(W, yy); g.stroke(); g.restore();
      g.fillStyle = color; g.font = `bold 10px ${FONT}`; g.textAlign = "left"; g.fillText(`${label} ${px}`, LBL + BARW * 0.62, yy - 6);
    };
    line(p.vah, "#7dd3fc", "VAH", 1, [4, 3]); line(p.val, "#7dd3fc", "VAL", 1, [4, 3]); line(p.poc, C.poc, "POC", 2);
    if (vwap != null && vwap <= hi && vwap >= rows[rows.length - 1].px) line(Math.floor(vwap / bucket) * bucket, C.vwap, "VWAP", 1, [8, 3]);
    if (last != null && last <= hi + bucket && last >= rows[rows.length - 1].px) {
      const yy = y(Math.floor(last / bucket) * bucket) + rowH / 2;
      g.strokeStyle = C.price; g.lineWidth = 1.6; g.beginPath(); g.moveTo(0, yy); g.lineTo(W, yy); g.stroke();
      g.fillStyle = C.price; g.fillRect(0, yy - 7, LBL - 2, 14); g.fillStyle = "#0b0f14"; g.font = `bold 10px ${FONT}`; g.textAlign = "left"; g.fillText(last.toFixed(2), 3, yy);
    }
  }, W, H, [rows, p, last, vwap]);
  useEffect(() => { const el = scroller.current; if (el && rows.length) el.scrollTop = Math.max(0, y(last ?? p.poc) - el.clientHeight / 2); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length]);
  if (!p?.ok) return <div className="rounded border border-zinc-800 bg-[#0a0d12] p-2"><Hdr id="profile-chart" t="Composite profile" src={p?.source} />{p?.error ?? "unavailable"}</div>;
  return (
    <div className="rounded border border-zinc-800 bg-[#0a0d12] p-2">
      <Hdr id="profile-chart" t={`Composite volume profile · ${p.days.length} days · POC ${p.poc} · VAH ${p.vah} · VAL ${p.val}`} src={p.source} />
      <div ref={scroller} className="max-h-[520px] overflow-auto rounded border border-zinc-900"><canvas ref={ref} data-testid="profile-canvas" /></div>
      <div className="mt-1 flex gap-3 text-[10px] text-zinc-500"><span className="text-sky-300">■ value area (70%)</span><span className="text-yellow-300">■ POC</span><span className="text-violet-300">■ TPO count (right)</span><span>{p.days.join(", ")}</span></div>
    </div>
  );
}

/** Plan + recorder levels for overlays (from config/tape-plan.json via API `chart`). */
export function chartLevels(chart: any): ChartLevel[] {
  return Array.isArray(chart?.levels) ? chart.levels : [];
}
