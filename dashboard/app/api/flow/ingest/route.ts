import { NextResponse, type NextRequest } from "next/server";
import { put } from "@vercel/blob";
import { sanitizeFlowData } from "@/lib/flowSanitize";
import { logIngestAttempt } from "@/lib/auditLog";

function constantTimeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function POST(request: NextRequest) {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0] || "unknown";
  const authHeader = request.headers.get("authorization");
  const expectedToken = process.env.FLOW_INGEST_TOKEN;
  
  if (!expectedToken) {
    console.error("[flow/ingest] FLOW_INGEST_TOKEN not configured");
    return NextResponse.json(
      { error: "Server misconfigured" },
      { status: 500 }
    );
  }
  
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    logIngestAttempt(ip, false, "missing_or_malformed_auth_header");
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401 }
    );
  }
  
  const token = authHeader.slice(7);
  
  if (!constantTimeCompare(token, expectedToken)) {
    logIngestAttempt(ip, false, "invalid_token");
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401 }
    );
  }
  
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON" },
      { status: 400 }
    );
  }
  
  const sanitized = sanitizeFlowData(body);
  
  if (!sanitized) {
    logIngestAttempt(ip, false, "validation_failed");
    return NextResponse.json(
      { 
        error: "Data failed validation",
        hint: "Check source data quality (price range, CVD bounds, bar integrity, timestamp age)"
      },
      { status: 400 }
    );
  }
  
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  
  if (!blobToken) {
    console.error("[flow/ingest] BLOB_READ_WRITE_TOKEN not configured");
    return NextResponse.json(
      { error: "Storage not configured" },
      { status: 500 }
    );
  }
  
  try {
    await put("flow/latest.json", JSON.stringify(sanitized), {
      access: "public",
      token: blobToken,
    });
    
    logIngestAttempt(ip, true);
    return NextResponse.json({ success: true, ts: sanitized.ts });
  } catch (err) {
    console.error("[flow/ingest] Failed to store blob:", err);
    logIngestAttempt(ip, false, "storage_failed");
    return NextResponse.json(
      { error: "Storage failed" },
      { status: 500 }
    );
  }
}
