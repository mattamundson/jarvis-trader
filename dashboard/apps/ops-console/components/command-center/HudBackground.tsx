"use client";
import { Canvas } from "@react-three/fiber";
import { ParticleField } from "./ParticleField";
import { ArcReactorPulse } from "./ArcReactorPulse";

export function HudBackground() {
  return (
    <div
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 0, opacity: 0.55 }}
    >
      <Canvas
        camera={{ position: [0, 0, 60], fov: 70 }}
        dpr={[1, 1.5]}
        gl={{ antialias: false, alpha: true }}
      >
        <ParticleField count={200} />
        <ArcReactorPulse />
      </Canvas>
    </div>
  );
}
