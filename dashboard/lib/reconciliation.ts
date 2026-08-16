export interface BrokerPosition {
  symbol: string;
  quantity: number;
  avg_price: number | null;
  market_price: number | null;
  unrealized_pnl: number | null;
  sec_type: string;
}

export interface PaperPosition {
  trade_id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  quantity: number;
  entry_price: number | null;
  entry_time: string | null;
}

export interface ReconciliationDiscrepancy {
  symbol: string | null;
  type: string; // "paper_only" | "paper_unverified" | "live_only" | "qty_mismatch" | "all_brokers_disconnected"
  detail: string;
  broker_family?: string;
  paper_qty?: number;
  live_qty?: number;
  delta?: number;
}

export interface BrokerPositionsResponse {
  ibkr: { connected: boolean; positions: BrokerPosition[] };
  schwab: { connected: boolean; positions: BrokerPosition[] };
  paper: { positions: PaperPosition[] };
  reconciliation: {
    discrepancies: ReconciliationDiscrepancy[];
    health: "ok" | "partial" | "blind";
    ibkr_queryable: boolean;
    schwab_queryable: boolean;
    last_checked: string;
  };
}

export interface ReconcileResult {
  ib_connected: boolean;
  matched: Array<{ symbol: string; quantity: number }>;
  ib_only: Array<{ symbol: string; quantity: number }>;
  paper_only: Array<{ symbol: string; quantity: number }>;
  paper_unverified: Array<{ symbol: string; quantity: number; broker_family?: string; detail?: string }>;
  mismatches: Array<{ symbol: string; paper_qty: number; ib_qty: number; delta: number }>;
  status: string;
  reconciled_at: string | null;
}

function signedPaperQty(p: PaperPosition): number {
  const qty = Math.abs(p.quantity);
  return p.direction === "LONG" ? qty : -qty;
}

/** Reshape GET /brokers/positions into the flat contract rendered by ReconciliationWidget. */
export function adaptBrokerPositionsReconciliation(data: BrokerPositionsResponse): ReconcileResult {
  const livePositions = [...data.ibkr.positions, ...data.schwab.positions];
  const liveQtyBySymbol = new Map<string, number>();
  for (const p of livePositions) {
    liveQtyBySymbol.set(p.symbol.toUpperCase(), (liveQtyBySymbol.get(p.symbol.toUpperCase()) ?? 0) + p.quantity);
  }

  const paperQtyBySymbol = new Map<string, number>();
  for (const p of data.paper.positions) {
    const sym = p.symbol.toUpperCase();
    paperQtyBySymbol.set(sym, (paperQtyBySymbol.get(sym) ?? 0) + signedPaperQty(p));
  }

  const { discrepancies } = data.reconciliation;
  const flaggedSymbols = new Set(discrepancies.map((d) => d.symbol).filter((s): s is string => !!s));

  const mismatches = discrepancies
    .filter((d) => d.type === "qty_mismatch" && d.symbol)
    .map((d) => ({
      symbol: d.symbol as string,
      paper_qty: d.paper_qty ?? 0,
      ib_qty: d.live_qty ?? 0,
      delta: d.delta ?? 0,
    }));

  const paper_only = discrepancies
    .filter((d) => d.type === "paper_only" && d.symbol)
    .map((d) => ({ symbol: d.symbol as string, quantity: paperQtyBySymbol.get(d.symbol as string) ?? 0 }));

  const paper_unverified = discrepancies
    .filter((d) => d.type === "paper_unverified" && d.symbol)
    .map((d) => ({
      symbol: d.symbol as string,
      quantity: paperQtyBySymbol.get(d.symbol as string) ?? 0,
      broker_family: d.broker_family,
      detail: d.detail,
    }));

  const ib_only = discrepancies
    .filter((d) => d.type === "live_only" && d.symbol)
    .map((d) => ({ symbol: d.symbol as string, quantity: liveQtyBySymbol.get(d.symbol as string) ?? 0 }));

  const matched: Array<{ symbol: string; quantity: number }> = [];
  for (const sym of liveQtyBySymbol.keys()) {
    if (paperQtyBySymbol.has(sym) && !flaggedSymbols.has(sym)) {
      matched.push({ symbol: sym, quantity: liveQtyBySymbol.get(sym) ?? 0 });
    }
  }

  let status: string;
  if (data.reconciliation.health === "blind") {
    status = "ib_disconnected";
  } else if (mismatches.length > 0) {
    status = "mismatch";
  } else if (paper_only.length > 0 || ib_only.length > 0) {
    status = "partial";
  } else if (paper_unverified.length > 0) {
    status = "unverified";
  } else if (matched.length === 0) {
    status = "no_positions";
  } else {
    status = "reconciled";
  }

  return {
    ib_connected: data.ibkr.connected,
    matched,
    ib_only,
    paper_only,
    paper_unverified,
    mismatches,
    status,
    reconciled_at: data.reconciliation.last_checked ?? null,
  };
}
