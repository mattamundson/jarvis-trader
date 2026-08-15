"use client";
import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

export function ArcReactorPulse() {
  const ring1Ref = useRef<THREE.Mesh>(null);
  const ring2Ref = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();

    if (ring1Ref.current) {
      (ring1Ref.current.material as THREE.MeshBasicMaterial).opacity =
        0.05 + 0.03 * Math.sin(t * 1.5);
      ring1Ref.current.rotation.z += 0.005;
    }

    if (ring2Ref.current) {
      (ring2Ref.current.material as THREE.MeshBasicMaterial).opacity =
        0.04 + 0.02 * Math.sin(t * 2.1 + Math.PI / 3);
      ring2Ref.current.rotation.z -= 0.007;
    }
  });

  return (
    <>
      {/* Inner pulsing ring */}
      <mesh ref={ring1Ref} position={[0, 0, -5]}>
        <ringGeometry args={[18, 19, 64]} />
        <meshBasicMaterial
          color="#00d4ff"
          transparent
          opacity={0.05}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Outer pulsing ring */}
      <mesh ref={ring2Ref} position={[0, 0, -5]}>
        <ringGeometry args={[24, 25.5, 64]} />
        <meshBasicMaterial
          color="#0099ff"
          transparent
          opacity={0.04}
          side={THREE.DoubleSide}
        />
      </mesh>
    </>
  );
}
