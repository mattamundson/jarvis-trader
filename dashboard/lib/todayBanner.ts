// Pure derivation for the /today status banner variant.
//
// Split out from app/today/page.tsx (a "use client" JSX file) so the logic
// can be covered by a plain node:test unit test without dragging in
// React/JSX (mirrors the honestTrades.ts / honestMetrics.ts split).
//
// GT-09: getBannerVariant used to collapse EVERY non-'ok' health.status into
// the alarming "ENGINE UNREACHABLE" banner -- including the normal
// 'degraded' state (e.g. a single LLM provider leg down while the engine
// itself, IBKR, and market data are all fine). That's misleading: a
// connected broker + fresh data feed means the engine is up and usable, just
// degraded. Now distinguishes "degraded but connected" from a genuinely
// unreachable/disconnected engine.

export type BannerVariant = "live_ok" | "paper_ok" | "degraded" | "unreachable";

// Minimal shape getBannerVariant needs off the /health response -- kept
// narrow (rather than importing the full HealthResponse type) so this stays
// a dependency-free pure function that's cheap to unit test.
export interface BannerHealthInput {
  status: string;
  live_trading: boolean;
  ibkr_connected: boolean;
  schwab_connected: boolean;
  ibkr_data_connected?: boolean | null;
  tradingview_mcp_healthy?: boolean | null;
}

export function getBannerVariant(
  health: BannerHealthInput | undefined,
  isError: boolean
): BannerVariant {
  // Genuinely unreachable: no response reached us at all (fetch/network
  // failure) -- the only case that truly means "cannot connect to engine".
  if (isError || !health) return "unreachable";

  // A live broker leg (execution) or a fresh market-data feed means the
  // engine is actually connected and usable, even when `status` isn't a
  // clean "ok".
  const brokerConnected = health.ibkr_connected || health.schwab_connected;
  // OR (not ??): IBKR's data leg can be explicitly `false` while TradingView
  // MCP still covers bars (see health_router.py's "data down (TV covers
  // bars)" case) -- either source being truthy counts as fresh data.
  const marketDataFresh =
    !!health.ibkr_data_connected || !!health.tradingview_mcp_healthy;

  if (health.status !== "ok") {
    // status flips to 'degraded' for reasons ranging from a single LLM
    // provider leg being down (engine/routers/health_router.py:
    // `status = "ok" if (db_ok and llm_path_healthy) else "degraded"`) to
    // the broker connection dropping entirely. Collapsing every non-'ok'
    // status into the alarming "ENGINE UNREACHABLE" banner is wrong when the
    // broker is connected and market data is flowing -- show the softer
    // "degraded but connected" message instead, and reserve "unreachable"
    // for when we truly have no broker/data leg to fall back on.
    return brokerConnected || marketDataFresh ? "degraded" : "unreachable";
  }

  // status === 'ok' but neither broker leg connected: execution/data leg
  // down even though the engine process itself is healthy.
  if (!brokerConnected) return "degraded";
  if (health.live_trading) return "live_ok";
  return "paper_ok";
}
