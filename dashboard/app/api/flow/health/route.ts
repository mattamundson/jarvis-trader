import { NextResponse } from "next/server";
import { head } from "@vercel/blob";
import { logHealthCheck } from "@/lib/healthLogger";
import { recordHealthCheck } from "@/lib/healthHistory";

export async function GET() {
  const startTime = Date.now();
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  
  if (!blobToken) {
    return NextResponse.json({
      status: "unknown",
      reason: "Blob not configured"
    }, { status: 503 });
  }
  
  try {
    const blob = await head("flow/latest.json", { token: blobToken });
    const ageMs = Date.now() - new Date(blob.uploadedAt).getTime();
    const ageSec = Math.floor(ageMs / 1000);
    
    let status: "live" | "stale" | "offline";
    if (ageSec < 10) status = "live";
    else if (ageSec < 120) status = "stale";
    else status = "offline";
    
    const responseTimeMs = Date.now() - startTime;
    const timestamp = new Date().toISOString();
    
    // Log to Vercel logs
    logHealthCheck({
      timestamp,
      status,
      age_seconds: ageSec,
      response_time_ms: responseTimeMs,
      source: "endpoint"
    });
    
    // Record in history for uptime tracking
    recordHealthCheck({
      timestamp,
      status,
      age_seconds: ageSec
    });
    
    return NextResponse.json({
      status,
      age_seconds: ageSec,
      last_update: blob.uploadedAt,
      size_bytes: blob.size,
    });
  } catch (err) {
    const responseTimeMs = Date.now() - startTime;
    const timestamp = new Date().toISOString();
    
    // Log error state
    logHealthCheck({
      timestamp,
      status: "offline",
      age_seconds: -1,
      response_time_ms: responseTimeMs,
      source: "endpoint"
    });
    
    // Record offline status
    recordHealthCheck({
      timestamp,
      status: "offline",
      age_seconds: -1
    });
    
    return NextResponse.json({
      status: "offline",
      reason: "Blob read failed",
      error: String(err)
    }, { status: 503 });
  }
}
