"use client";
import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

export function ParticleField({ count = 200 }: { count?: number }) {
  // Particles — use imperative geometry to avoid JSX bufferAttribute issues
  const particleRef = useRef<THREE.Points>(null);

  const particleGeometry = useMemo(() => {
    const arr = new Float32Array(count * 3);
    const vel: Array<{ x: number; y: number }> = [];
    for (let i = 0; i < count; i++) {
      arr[i * 3]     = (Math.random() - 0.5) * 180;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 100;
      arr[i * 3 + 2] = -20 - Math.random() * 30;
      vel.push({
        x: (Math.random() - 0.5) * 0.05,
        y: (Math.random() - 0.5) * 0.03,
      });
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    // Store velocities on geometry userData so animate loop can access them
    (geo as THREE.BufferGeometry & { userData: { vel: typeof vel } }).userData.vel = vel;
    return geo;
  }, [count]);

  // Grid lines — two depth layers matching the original HTML
  const gridGeo1 = useMemo(() => {
    const verts: number[] = [];
    for (let i = -80; i <= 80; i += 6) {
      verts.push(i, -40, -50, i, 40, -50);
      verts.push(-80, i * 0.5, -50, 80, i * 0.5, -50);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    return geo;
  }, []);

  const gridGeo2 = useMemo(() => {
    const verts: number[] = [];
    for (let i = -80; i <= 80; i += 6) {
      verts.push(i, -40, -80, i, 40, -80);
      verts.push(-80, i * 0.5, -80, 80, i * 0.5, -80);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    return geo;
  }, []);

  // Hex ring refs — 4 rings matching the original HTML
  const ring0 = useRef<THREE.Mesh>(null);
  const ring1 = useRef<THREE.Mesh>(null);
  const ring2 = useRef<THREE.Mesh>(null);
  const ring3 = useRef<THREE.Mesh>(null);
  const ringRefs = [ring0, ring1, ring2, ring3];

  useFrame(() => {
    // Drift particles with velocity wrap-around
    if (particleRef.current) {
      const geo = particleRef.current.geometry;
      const pos = geo.attributes.position.array as Float32Array;
      const vel = (geo.userData as { vel: Array<{ x: number; y: number }> }).vel;
      for (let i = 0; i < count; i++) {
        pos[i * 3]     += vel[i].x;
        pos[i * 3 + 1] += vel[i].y;
        if (pos[i * 3] > 90)    pos[i * 3] = -90;
        if (pos[i * 3] < -90)   pos[i * 3] = 90;
        if (pos[i * 3 + 1] > 50) pos[i * 3 + 1] = -50;
        if (pos[i * 3 + 1] < -50) pos[i * 3 + 1] = 50;
      }
      geo.attributes.position.needsUpdate = true;
    }

    // Rotate hex rings at their individual speeds
    const speeds = [0.002, 0.003, 0.004, 0.005];
    ringRefs.forEach((ref, i) => {
      if (ref.current) {
        ref.current.rotation.z += speeds[i];
      }
    });
  });

  // Hex ring configs: [radius, x-offset, y-offset, color] — mirroring HTML original
  const hexRings = [
    { r: 15,  x: -20, y: 10,  color: 0x00d4ff },
    { r: 27,  x: -12, y: 5,   color: 0x00ff88 },
    { r: 39,  x: -4,  y: 0,   color: 0x00d4ff },
    { r: 51,  x:  4,  y: -5,  color: 0x00ff88 },
  ] as const;

  return (
    <>
      {/* Floating data particles */}
      <points ref={particleRef} geometry={particleGeometry}>
        <pointsMaterial
          color="#00d4ff"
          size={0.5}
          transparent
          opacity={0.4}
          sizeAttenuation
        />
      </points>

      {/* Grid — near layer */}
      <lineSegments geometry={gridGeo1}>
        <lineBasicMaterial color="#0c2438" transparent opacity={0.4} />
      </lineSegments>

      {/* Grid — far layer */}
      <lineSegments geometry={gridGeo2}>
        <lineBasicMaterial color="#061220" transparent opacity={0.2} />
      </lineSegments>

      {/* Hex overlay rings */}
      {hexRings.map((cfg, i) => (
        <mesh
          key={i}
          ref={ringRefs[i]}
          position={[cfg.x, cfg.y, -30]}
          rotation={[0, 0, i * 0.5]}
        >
          <ringGeometry args={[cfg.r - 0.2, cfg.r, 6]} />
          <meshBasicMaterial
            color={cfg.color}
            side={THREE.DoubleSide}
            transparent
            opacity={0.04}
          />
        </mesh>
      ))}
    </>
  );
}
