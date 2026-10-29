// Optional Vercel KV persistence for health history
// Gracefully degrades to in-memory only if KV not configured
import type { HealthRecord } from "./healthHistory";

// Vercel KV is optional — check at runtime
let kvAvailable = false;
let kv: any = null;

try {
  // Dynamic import to avoid build errors when @vercel/kv not installed
  kv = require("@vercel/kv");
  kvAvailable = !!process.env.KV_REST_API_URL && !!process.env.KV_REST_API_TOKEN;
} catch {
  kvAvailable = false;
}

const KV_KEY_PREFIX = "flow:health:";
const KV_RETENTION_DAYS = 30;

export async function persistHealthRecord(record: HealthRecord): Promise<boolean> {
  if (!kvAvailable || !kv) {
    return false; // Graceful degradation — not an error
  }
  
  try {
    const key = `${KV_KEY_PREFIX}${record.timestamp}`;
    const ttl = KV_RETENTION_DAYS * 24 * 60 * 60; // 30 days in seconds
    
    await kv.setex(key, ttl, JSON.stringify(record));
    return true;
  } catch (err) {
    console.warn("[kvHistory] Failed to persist to KV (non-fatal):", err);
    return false;
  }
}

export async function fetchHistoricalRecords(hours: number = 24): Promise<HealthRecord[]> {
  if (!kvAvailable || !kv) {
    return []; // Graceful degradation
  }
  
  try {
    const cutoff = new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
    
    // Scan for all health records within time window
    // This is inefficient at scale — consider time-series DB (TimescaleDB, InfluxDB) for production
    let cursor = "0";
    const records: HealthRecord[] = [];
    
    do {
      const [nextCursor, keys] = await kv.scan(cursor, {
        match: `${KV_KEY_PREFIX}*`,
        count: 100
      });
      
      for (const key of keys) {
        const data = await kv.get(key);
        if (data) {
          const record = JSON.parse(data);
          if (record.timestamp >= cutoff) {
            records.push(record);
          }
        }
      }
      
      cursor = nextCursor;
    } while (cursor !== "0");
    
    return records.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  } catch (err) {
    console.error("[kvHistory] Failed to fetch from KV:", err);
    return [];
  }
}

export function isKvConfigured(): boolean {
  return kvAvailable;
}
