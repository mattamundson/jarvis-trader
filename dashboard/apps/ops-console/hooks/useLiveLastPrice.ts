"use client";

import { useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";

/**
 * Latest real-time price for `symbol` from the engine `price_update` WS event.
 *
 * Returns `null` until a tick arrives — so chart consumers fall back to their
 * polled bars when no `price_update` producer is active (the engine emitter is
 * opt-in). Feed the result into `CandlestickChart`'s `livePrice` prop to update
 * the last candle between bar fetches.
 */
export function useLiveLastPrice(symbol: string | null | undefined): number | null {
  const [price, setPrice] = useState<number | null>(null);
  const wantRef = useRef<string>("");
  wantRef.current = (symbol ?? "").trim().toUpperCase();

  // Drop a stale price when the symbol changes (or charting is disabled).
  useEffect(() => {
    setPrice(null);
  }, [symbol]);

  useWebSocket(undefined, (e) => {
    if (e.type !== "price_update") return;
    const want = wantRef.current;
    if (!want) return;
    const got = (e.symbol ?? "").trim().toUpperCase();
    // Match exact or front-month/continuous variants (MES ⇄ MESU2026 ⇄ MES1!).
    if (got === want || got.startsWith(want) || want.startsWith(got)) {
      if (typeof e.price === "number" && Number.isFinite(e.price)) {
        setPrice(e.price);
      }
    }
  });

  return price;
}
