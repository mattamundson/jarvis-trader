import type { FlowSnapshot } from "./flowTypes";

export function sanitizeFlowData(data: unknown): FlowSnapshot | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  
  const raw = data as Record<string, unknown>;
  
  if (typeof raw.ts !== "string") {
    return null;
  }
  
  const es = raw.es as Record<string, unknown> | undefined;
  const nq = raw.nq as Record<string, unknown> | undefined;
  const gex = raw.gex as Record<string, unknown> | undefined;
  const gates = raw.gates as Array<unknown> | undefined;
  
  if (!es || !nq || !gex || !Array.isArray(gates)) {
    return null;
  }
  
  if (
    typeof es.last !== "number" ||
    typeof es.vwap !== "number" ||
    typeof es.onHigh !== "number" ||
    typeof es.onLow !== "number" ||
    typeof es.cvd !== "number" ||
    typeof es.cvdLow !== "number" ||
    !Array.isArray(es.bars1m) ||
    !Array.isArray(es.deltaAtPrice) ||
    !Array.isArray(es.bigPrints)
  ) {
    return null;
  }
  
  if (typeof nq.last !== "number" || typeof nq.vwap !== "number") {
    return null;
  }
  
  if (
    typeof gex.callWall !== "number" ||
    typeof gex.putWall !== "number" ||
    typeof gex.flip !== "number" ||
    typeof gex.pin !== "number" ||
    typeof gex.asOf !== "string"
  ) {
    return null;
  }
  
  const sanitizedBars = es.bars1m.map((bar: unknown) => {
    const b = bar as Record<string, unknown>;
    const base = {
      ts: String(b.ts),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume),
    };

    // Optional bidAtPrice / askAtPrice validation
    if (b.bidAtPrice && typeof b.bidAtPrice === "object" && !Array.isArray(b.bidAtPrice)) {
      const bidMap = b.bidAtPrice as Record<string, unknown>;
      const entries = Object.entries(bidMap);
      
      if (entries.length > 0 && entries.length <= 400) {
        const validBids: Record<number, number> = {};
        let allValid = true;
        
        for (const [price, lots] of entries) {
          const p = Number(price);
          const l = Number(lots);
          
          if (isNaN(p) || isNaN(l) || l < 0) {
            allValid = false;
            break;
          }
          
          validBids[p] = l;
        }
        
        if (allValid) {
          (base as Record<string, unknown>).bidAtPrice = validBids;
        }
      }
    }

    if (b.askAtPrice && typeof b.askAtPrice === "object" && !Array.isArray(b.askAtPrice)) {
      const askMap = b.askAtPrice as Record<string, unknown>;
      const entries = Object.entries(askMap);
      
      if (entries.length > 0 && entries.length <= 400) {
        const validAsks: Record<number, number> = {};
        let allValid = true;
        
        for (const [price, lots] of entries) {
          const p = Number(price);
          const l = Number(lots);
          
          if (isNaN(p) || isNaN(l) || l < 0) {
            allValid = false;
            break;
          }
          
          validAsks[p] = l;
        }
        
        if (allValid) {
          (base as Record<string, unknown>).askAtPrice = validAsks;
        }
      }
    }

    return base;
  });
  
  const sanitizedDelta = es.deltaAtPrice.map((d: unknown) => {
    const delta = d as Record<string, unknown>;
    return {
      price: Number(delta.price),
      bidLots: Number(delta.bidLots),
      askLots: Number(delta.askLots),
    };
  });
  
  const sanitizedPrints = es.bigPrints.map((p: unknown) => {
    const print = p as Record<string, unknown>;
    return {
      ts: String(print.ts),
      price: Number(print.price),
      lots: Number(print.lots),
      side: String(print.side) as "bid" | "ask",
    };
  });
  
  const sanitizedGates = gates.map((g: unknown) => {
    const gate = g as Record<string, unknown>;
    return {
      level: Number(gate.level),
      status: String(gate.status) as "untested" | "testing" | "broken",
      closeCount: Number(gate.closeCount),
    };
  });
  
  // Quality validation gates
  const errors: string[] = [];
  
  // ES price must be realistic (ES trades ~1000-10000 range)
  if (es.last < 1000 || es.last > 10000) {
    errors.push(`ES price unrealistic: ${es.last}`);
  }
  
  // CVD magnitude check (absolute value < 10000)
  if (Math.abs(es.cvd) > 10000) {
    errors.push(`CVD magnitude unrealistic: ${es.cvd}`);
  }
  
  // Price/VWAP divergence check (difference < 100 points)
  if (Math.abs(es.last - es.vwap) > 100) {
    errors.push(`Price/VWAP divergence: ${Math.abs(es.last - es.vwap)}`);
  }
  
  // Must have bars
  if (sanitizedBars.length === 0) {
    errors.push("No bars");
  }
  
  // Bar integrity check
  if (sanitizedBars.some(b => b.volume < 0 || b.high < b.low)) {
    errors.push("Invalid bars");
  }
  
  // Timestamp age check (within 5 minutes forward, 60 seconds back)
  const tsAge = (Date.now() - new Date(raw.ts).getTime()) / 1000;
  if (tsAge > 300 || tsAge < -60) {
    errors.push(`Timestamp age suspicious: ${Math.round(tsAge)}s`);
  }
  
  if (errors.length > 0) {
    console.warn("[flowSanitize] Rejected:", errors);
    return null;
  }
  
  return {
    ts: raw.ts,
    fixture: raw.fixture === true ? true : undefined,
    es: {
      last: es.last,
      vwap: es.vwap,
      onHigh: es.onHigh,
      onLow: es.onLow,
      cvd: es.cvd,
      cvdLow: es.cvdLow,
      bars1m: sanitizedBars,
      deltaAtPrice: sanitizedDelta,
      bigPrints: sanitizedPrints,
    },
    nq: {
      last: nq.last,
      vwap: nq.vwap,
    },
    gex: {
      callWall: gex.callWall,
      putWall: gex.putWall,
      flip: gex.flip,
      pin: gex.pin,
      asOf: gex.asOf,
    },
    gates: sanitizedGates,
  };
}
