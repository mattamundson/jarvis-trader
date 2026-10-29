import type { FlowSnapshot } from "./flowTypes";

// In-memory last-known-good cache
// Serves stale data with warning if blob is unreachable
let lastKnownGood: FlowSnapshot | null = null;
let lastKnownGoodTime: number = 0;

export function cacheFlowData(data: FlowSnapshot) {
  lastKnownGood = data;
  lastKnownGoodTime = Date.now();
}

export function getLastKnownGood(): { 
  data: FlowSnapshot | null; 
  age_seconds: number;
  is_stale: boolean;
} {
  if (!lastKnownGood) {
    return { data: null, age_seconds: 0, is_stale: false };
  }
  
  const ageSeconds = Math.floor((Date.now() - lastKnownGoodTime) / 1000);
  const isStale = ageSeconds > 300; // > 5 minutes
  
  return {
    data: lastKnownGood,
    age_seconds: ageSeconds,
    is_stale: isStale
  };
}

export function hasCache(): boolean {
  return lastKnownGood !== null;
}
