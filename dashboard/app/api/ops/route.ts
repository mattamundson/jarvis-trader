import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import type { OpsFeedData } from "@/lib/opsTypes";
import type { HermesGatesData } from "@/lib/hermesTypes";
import { adaptHermesToOps } from "@/lib/hermesAdapter";
import { isOpsEnabled } from "@/lib/opsAuth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function getOpsFeedUrl(): string | null {
  return process.env.OPS_FEED_URL ?? null;
}

function getOpsGatesPath(): string | null {
  return process.env.OPS_GATES_PATH ?? null;
}

// Clearly fake fixture data for when OPS_FEED_URL is not set
function getFakeFixture(): OpsFeedData {
  return {
    proof_bar: {
      clean_paper_sessions: 7,
      scored_setups: 14,
      avg_r: 1.8,
      rule_breaks: 0,
    },
    strikes: [
      {
        date: "2026-10-20",
        reason: "Late entry on MES long setup",
        severity: "minor",
      },
      {
        date: "2026-10-15",
        reason: "Oversized position by 10%",
        severity: "major",
      },
    ],
    lockout: {
      active: false,
      end_date: null,
      reason: null,
    },
    today_journal: [
      {
        date: "2026-10-27",
        symbol: "MES",
        direction: "long",
        entry_price: 5890.25,
        exit_price: 5902.75,
        r_multiple: 2.1,
        notes: "Clean breakout, held above VWAP",
      },
      {
        date: "2026-10-27",
        symbol: "MES",
        direction: "short",
        entry_price: 5885.5,
        exit_price: null,
        r_multiple: null,
        notes: "Live position, watching 5880 support",
      },
    ],
    system_health: {
      tick_recorder_last_write: "2026-10-27T05:34:12Z",
      flow_feed_age_seconds: 45,
      ib_gateway_status: "connected",
    },
    timestamp: new Date().toISOString(),
  };
}

export async function GET() {
  if (!isOpsEnabled()) {
    return NextResponse.json(
      { error: "ops_disabled" },
      { status: 404 }
    );
  }

  // Try local file path first
  const gatesPath = getOpsGatesPath();
  if (gatesPath) {
    try {
      const raw = await fs.readFile(gatesPath, "utf-8");
      const hermes = JSON.parse(raw) as HermesGatesData;
      const adapted = adaptHermesToOps(hermes);
      return NextResponse.json(adapted);
    } catch (error) {
      // Fall through to URL fetch or fixture
    }
  }

  // Try remote URL
  const feedUrl = getOpsFeedUrl();

  if (!feedUrl) {
    return NextResponse.json(getFakeFixture());
  }

  try {
    const res = await fetch(feedUrl, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });

    if (!res.ok) {
      throw new Error(`Feed fetch failed: ${res.status}`);
    }

    const data = await res.json();
    
    // Check if it's Hermes format (has pulled_ct field)
    if ("pulled_ct" in data && "go_live" in data) {
      const adapted = adaptHermesToOps(data as HermesGatesData);
      return NextResponse.json(adapted);
    }
    
    // Otherwise assume it's already OpsFeedData format
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        error: "ops_feed_failed",
        message: error instanceof Error ? error.message : "Unknown error",
        fallback: getFakeFixture(),
      },
      { status: 502 }
    );
  }
}
