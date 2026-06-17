"use client";

import { useEffect, useRef } from "react";
import { useEngineHealth } from "@/lib/engine-context";
import { Wifi } from "lucide-react";

/**
 * Listens for engine offline → online transitions and shows a
 * brief "Engine reconnected" toast at the bottom-right corner.
 */
export function EngineReconnectToast() {
  const { isOffline } = useEngineHealth();
  const wasOffline = useRef(false);
  const toastRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (wasOffline.current && !isOffline) {
      // Reconnected — show toast
      const el = toastRef.current;
      if (el) {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
        setTimeout(() => {
          if (el) {
            el.style.opacity = "0";
            el.style.transform = "translateY(8px)";
          }
        }, 3000);
      }
    }
    wasOffline.current = isOffline ?? false;
  }, [isOffline]);

  return (
    <div
      ref={toastRef}
      style={{
        position: "fixed",
        bottom: "24px",
        right: "24px",
        zIndex: 9999,
        opacity: 0,
        transform: "translateY(8px)",
        transition: "opacity 0.3s ease, transform 0.3s ease",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          backgroundColor: "#0a0a0a",
          border: "1px solid #00ff88",
          borderRadius: "8px",
          padding: "10px 16px",
          color: "#00ff88",
          fontSize: "12px",
          fontFamily: "monospace",
          fontWeight: 600,
        }}
      >
        <Wifi size={14} />
        Engine reconnected
      </div>
    </div>
  );
}
