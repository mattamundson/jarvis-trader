"use client";

import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { fetchEngine } from "@/lib/api";
import type { ChartSymbol } from "@/hooks/useChartData";

// Multi-timeframe ridge surface: each row is one timeframe's close series,
// resampled to a common column count and normalized so its shape is visible.
const TF_ROWS: { tf: string; days: number }[] = [
  { tf: "5m", days: 3 },
  { tf: "15m", days: 7 },
  { tf: "1h", days: 30 },
  { tf: "4h", days: 60 },
  { tf: "1d", days: 365 },
];
const COLS = 64;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function resample(values: number[], k: number): number[] {
  if (values.length === 0) return new Array(k).fill(0);
  if (values.length === 1) return new Array(k).fill(values[0]);
  const out: number[] = [];
  for (let i = 0; i < k; i++) {
    const pos = (i / (k - 1)) * (values.length - 1);
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    out.push(lerp(values[lo], values[hi], pos - lo));
  }
  return out;
}

function normalize(values: number[]): number[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values.map((v) => (v - min) / range);
}

function heatColor(t: number): [number, number, number] {
  const c0 = [0.0, 0.2, 0.4]; // deep blue (low)
  const c1 = [0.0, 0.83, 1.0]; // cyan (mid)
  const c2 = [1.0, 0.27, 0.4]; // red (high)
  if (t < 0.5) {
    const u = t / 0.5;
    return [lerp(c0[0], c1[0], u), lerp(c0[1], c1[1], u), lerp(c0[2], c1[2], u)];
  }
  const u = (t - 0.5) / 0.5;
  return [lerp(c1[0], c2[0], u), lerp(c1[1], c2[1], u), lerp(c1[2], c2[2], u)];
}

type RawBar = { close?: number | string };

async function fetchTerrain(symbol: ChartSymbol): Promise<number[][]> {
  const rows = await Promise.all(
    TF_ROWS.map(({ tf, days }) =>
      fetchEngine<unknown>(
        `/analyze/bars/${symbol}?timeframe=${tf}&days=${days}&futures=true`,
      )
        .then((raw) => {
          const arr: RawBar[] = Array.isArray(raw)
            ? (raw as RawBar[])
            : ((raw as { bars?: RawBar[] })?.bars ?? []);
          const closes = arr
            .map((b) => Number(b.close))
            .filter((n) => Number.isFinite(n));
          return closes.length ? normalize(resample(closes, COLS)) : null;
        })
        .catch(() => null),
    ),
  );
  return rows.filter((r): r is number[] => r != null);
}

function buildGeometry(grid: number[][]): THREE.BufferGeometry {
  const geo = new THREE.BufferGeometry();
  const rows = grid.length;
  const cols = grid[0].length;
  const W = 2.6;
  const D = 1.7;
  const H = 0.7;

  const positions: number[] = [];
  const colors: number[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const h = grid[r][c];
      positions.push(
        (c / (cols - 1) - 0.5) * W,
        h * H,
        (r / (rows - 1) - 0.5) * D,
      );
      const [cr, cg, cb] = heatColor(h);
      colors.push(cr, cg, cb);
    }
  }

  const indices: number[] = [];
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const a = r * cols + c;
      const b = a + 1;
      const cc = (r + 1) * cols + c;
      const d = cc + 1;
      indices.push(a, cc, b, b, cc, d);
    }
  }

  geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

function Surface({ grid }: { grid: number[][] }) {
  const geometry = useMemo(() => buildGeometry(grid), [grid]);
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        side: THREE.DoubleSide,
        roughness: 0.55,
        metalness: 0.2,
        flatShading: false,
      }),
    [],
  );
  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => material.dispose(), [material]);
  return <mesh geometry={geometry} material={material} />;
}

function Controls() {
  const { camera, gl } = useThree();
  const ref = useRef<OrbitControls | null>(null);
  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1.5;
    controls.maxDistance = 6;
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.6;
    ref.current = controls;
    return () => controls.dispose();
  }, [camera, gl]);
  useFrame(() => ref.current?.update());
  return null;
}

interface PriceTerrain3DProps {
  symbol: ChartSymbol;
  height?: number;
}

/**
 * Greenfield 3D financial view: a multi-timeframe price "terrain" for the given
 * symbol. X = time (resampled), Z = timeframe (5m → 1d ridges), Y = normalized
 * close, color = heat by height. Orbit/zoom via mouse; auto-rotates idle.
 */
export function PriceTerrain3D({ symbol, height = 460 }: PriceTerrain3DProps) {
  const { data: grid, isLoading } = useSWR(
    ["price-terrain", symbol],
    () => fetchTerrain(symbol),
    { refreshInterval: 120_000, revalidateOnFocus: false },
  );

  const ready = grid && grid.length >= 2 && grid[0]?.length === COLS;

  return (
    <div style={{ height }} className="relative w-full overflow-hidden rounded-lg bg-[#060d1a]">
      {ready ? (
        <Canvas camera={{ position: [0, 1.5, 2.7], fov: 55 }} dpr={[1, 2]}>
          <color attach="background" args={["#060d1a"]} />
          <ambientLight intensity={0.65} />
          <directionalLight position={[3, 5, 2]} intensity={0.85} />
          <directionalLight position={[-3, 2, -2]} intensity={0.3} color="#00d4ff" />
          <Surface grid={grid} />
          <Controls />
        </Canvas>
      ) : (
        <div className="flex h-full items-center justify-center text-sm font-mono text-slate-500">
          {isLoading ? "Building terrain…" : `No bar data for ${symbol}`}
        </div>
      )}
      <div className="pointer-events-none absolute bottom-2 left-3 text-[10px] font-mono text-cyan-700/80">
        {symbol} · X=time · Z=timeframe(5m→1d) · Y=norm close
      </div>
    </div>
  );
}
