import { NextResponse } from "next/server";
import { head } from "@vercel/blob";

export async function GET() {
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
    
    return NextResponse.json({
      status,
      age_seconds: ageSec,
      last_update: blob.uploadedAt,
      size_bytes: blob.size,
    });
  } catch (err) {
    return NextResponse.json({
      status: "offline",
      reason: "Blob read failed",
      error: String(err)
    }, { status: 503 });
  }
}
