"use client";

import { useEffect, useState } from "react";
import { Send, Shield, Loader2 } from "lucide-react";
import { postEngine, fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Trade Execution Card — Mission Control.
 *
 * Paper-only trading panel for MES (the one active paper symbol).
 * Every order routes through the engine's SafetyLayer, which enforces:
 *   - PAPER MODE only (live_trading=false)
 *   - Kill-switch gate
 *   - Drawdown halt
 *   - Position limits
 *   - DO_NOT_TRADE_SYMBOLS
 *
 * ENDPOINTS USED:
 *   POST /orders/submit  — submit a paper order
 *   GET  /orders/status   — current order + position state
 *   GET  /portfolio/paper/performance — P&L context
 *
 * The card never routes real money: live_trading is false and the engine
 * safety layer blocks any live order.  This is a CONTROL card — it MUTATES
 * state (creates paper orders) — unlike every other widget on Mission Control
 * which is read-only.
 */

type OrderSide = "BUY" | "SELL";

interface OrderState {
  symbol: string;
  side: OrderSide;
  quantity: number;
  orderType: "MKT" | "LMT";
  limitPrice: string;
  submitting: boolean;
  lastResult: string | null;
  lastError: string | null;
}

interface PositionInfo {
  symbol: string;
  quantity: number;
  avgPrice: number | null;
  pnl: number | null;
}

interface ExecutionState {
  positions: PositionInfo[];
  equity: number | null;
  killSwitch: boolean;
  drawdown: number | null;
  loading: boolean;
}

const DEFAULT_ORDER: OrderState = {
  symbol: "MES",
  side: "BUY",
  quantity: 1,
  orderType: "MKT",
  limitPrice: "",
  submitting: false,
  lastResult: null,
  lastError: null,
};

export function TradeExecutionCard() {
  const [order, setOrder] = useState<OrderState>(DEFAULT_ORDER);
  const [exec, setExec] = useState<ExecutionState>({
    positions: [],
    equity: null,
    killSwitch: false,
    drawdown: null,
    loading: true,
  });

  // Poll execution state every NORMAL interval.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [posData, perfData] = await Promise.all([
          fetchEngine<Record<string, unknown>>("/orders/status").catch(() => null),
          fetchEngine<Record<string, unknown>>("/portfolio/paper/performance").catch(() => null),
        ]);
        if (cancelled) return;
        const rawPositions = (posData as any)?.positions ?? [];
        setExec({
          positions: Array.isArray(rawPositions)
            ? rawPositions.map((p: any) => ({
                symbol: p.symbol ?? p.contract ?? "—",
                quantity: p.quantity ?? p.position ?? 0,
                avgPrice: p.avg_price ?? p.averagePrice ?? null,
                pnl: p.unrealized_pnl ?? p.pnl ?? null,
              }))
            : [],
          equity: (perfData as any)?.equity ?? (perfData as any)?.portfolio_equity ?? null,
          killSwitch: !!(posData as any)?.kill_switch_active,
          drawdown: (perfData as any)?.drawdown_pct ?? (perfData as any)?.drawdown ?? null,
          loading: false,
        });
      } catch {
        if (!cancelled) setExec((s) => ({ ...s, loading: false }));
      }
    }
    load();
    const interval = setInterval(load, POLL_INTERVAL.NORMAL);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  async function submitOrder() {
    if (order.submitting) return;
    setOrder((s) => ({ ...s, submitting: true, lastResult: null, lastError: null }));
    try {
      const body: Record<string, unknown> = {
        symbol: order.symbol,
        side: order.side,
        quantity: order.quantity,
        order_type: order.orderType.toLowerCase(),
      };
      if (order.orderType === "LMT" && order.limitPrice) {
        body.limit_price = parseFloat(order.limitPrice);
      }
      const result = await postEngine<Record<string, unknown>>("/orders/submit", body);
      setOrder((s) => ({
        ...s,
        submitting: false,
        lastResult: (result as any)?.order_id ?? (result as any)?.message ?? "Order submitted",
        lastError: null,
      }));
    } catch (e) {
      setOrder((s) => ({
        ...s,
        submitting: false,
        lastError: e instanceof Error ? e.message : "submit failed",
        lastResult: null,
      }));
    }
  }

  const killSwitchActive = exec.killSwitch;
  const ddPct = exec.drawdown;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Send className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">Trade Execution</h3>
        <Badge variant="info" className="ml-auto text-[10px]">
          PAPER
        </Badge>
      </div>

      {killSwitchActive ? (
        <div className="space-y-2 border border-bear/30 bg-bear/5 rounded p-3">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-bear" />
            <span className="text-xs font-semibold text-bear">KILL SWITCH ACTIVE</span>
          </div>
          <p className="text-[10px] text-muted-foreground">
            No orders can be submitted while the kill switch is active.
            Drawdown: {ddPct != null ? `${ddPct.toFixed(2)}%` : "—"}.
          </p>
        </div>
      ) : (
        <>
          {/* Order form */}
          <div className="grid grid-cols-2 gap-2">
            {/* Symbol */}
            <div>
              <label className="text-[10px] text-muted-foreground">Symbol</label>
              <select
                className="w-full mt-0.5 rounded border border-border bg-background text-xs font-mono px-2 py-1 text-foreground"
                value={order.symbol}
                onChange={(e) => setOrder((s) => ({ ...s, symbol: e.target.value }))}
              >
                <option value="MES">MES</option>
                <option value="SPY">SPY</option>
                <option value="QQQ">QQQ</option>
              </select>
            </div>
            {/* Side */}
            <div>
              <label className="text-[10px] text-muted-foreground">Side</label>
              <div className="flex gap-1 mt-0.5">
                <button
                  className={`flex-1 rounded text-xs font-mono px-2 py-1 border ${
                    order.side === "BUY"
                      ? "bg-bull/15 text-bull border-bull/30"
                      : "bg-background text-muted-foreground border-border"
                  }`}
                  onClick={() => setOrder((s) => ({ ...s, side: "BUY" }))}
                >
                  BUY
                </button>
                <button
                  className={`flex-1 rounded text-xs font-mono px-2 py-1 border ${
                    order.side === "SELL"
                      ? "bg-bear/15 text-bear border-bear/30"
                      : "bg-background text-muted-foreground border-border"
                  }`}
                  onClick={() => setOrder((s) => ({ ...s, side: "SELL" }))}
                >
                  SELL
                </button>
              </div>
            </div>
            {/* Quantity */}
            <div>
              <label className="text-[10px] text-muted-foreground">Qty</label>
              <input
                type="number"
                min={1}
                max={10}
                className="w-full mt-0.5 rounded border border-border bg-background text-xs font-mono px-2 py-1 text-foreground"
                value={order.quantity}
                onChange={(e) => setOrder((s) => ({ ...s, quantity: Math.max(1, parseInt(e.target.value) || 1) }))}
              />
            </div>
            {/* Order type */}
            <div>
              <label className="text-[10px] text-muted-foreground">Type</label>
              <div className="flex gap-1 mt-0.5">
                <button
                  className={`flex-1 rounded text-xs font-mono px-2 py-1 border ${
                    order.orderType === "MKT"
                      ? "bg-accent/15 text-accent border-accent/30"
                      : "bg-background text-muted-foreground border-border"
                  }`}
                  onClick={() => setOrder((s) => ({ ...s, orderType: "MKT" }))}
                >
                  MKT
                </button>
                <button
                  className={`flex-1 rounded text-xs font-mono px-2 py-1 border ${
                    order.orderType === "LMT"
                      ? "bg-accent/15 text-accent border-accent/30"
                      : "bg-background text-muted-foreground border-border"
                  }`}
                  onClick={() => setOrder((s) => ({ ...s, orderType: "LMT" }))}
                >
                  LMT
                </button>
              </div>
            </div>
          </div>

          {/* Limit price (only for LMT) */}
          {order.orderType === "LMT" && (
            <div>
              <label className="text-[10px] text-muted-foreground">Limit Price</label>
              <input
                type="number"
                step="0.25"
                className="w-full mt-0.5 rounded border border-border bg-background text-xs font-mono px-2 py-1 text-foreground"
                value={order.limitPrice}
                placeholder="e.g. 7800.00"
                onChange={(e) => setOrder((s) => ({ ...s, limitPrice: e.target.value }))}
              />
            </div>
          )}

          {/* Submit button */}
          <button
            className={`w-full rounded text-xs font-semibold px-3 py-2 flex items-center justify-center gap-2 ${
              order.submitting
                ? "bg-muted text-muted-foreground cursor-not-allowed"
                : order.side === "BUY"
                ? "bg-bull/15 text-bull border border-bull/30 hover:bg-bull/25"
                : "bg-bear/15 text-bear border border-bear/30 hover:bg-bear/25"
            }`}
            disabled={order.submitting || killSwitchActive}
            onClick={submitOrder}
          >
            {order.submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            {order.submitting
              ? "Submitting…"
              : `${order.side} ${order.quantity} ${order.symbol} ${order.orderType}`}
          </button>

          {/* Result / error feedback */}
          {order.lastResult && (
            <p className="text-[10px] text-bull font-mono">{order.lastResult}</p>
          )}
          {order.lastError && (
            <p className="text-[10px] text-bear font-mono">{order.lastError}</p>
          )}
        </>
      )}

      {/* Position summary */}
      <div className="border-t border-border pt-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground">Positions</span>
          <span className="text-[10px] font-mono text-foreground">
            {exec.loading ? "…" : exec.positions.length === 0 ? "None" : `${exec.positions.length} open`}
          </span>
        </div>
        {exec.positions.length > 0 && (
          <div className="mt-1 space-y-1">
            {exec.positions.map((p, i) => (
              <div key={i} className="flex items-center justify-between text-[10px]">
                <span className="font-mono text-foreground">
                  {p.quantity > 0 ? "+" : ""}{p.quantity} {p.symbol}
                </span>
                <span className={`font-mono ${(p.pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>
                  {p.pnl != null ? `$${p.pnl.toFixed(2)}` : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
        {exec.equity != null && (
          <div className="flex items-center justify-between mt-1 text-[10px]">
            <span className="text-muted-foreground">Equity</span>
            <span className="font-mono text-foreground">${exec.equity.toFixed(2)}</span>
          </div>
        )}
      </div>
    </div>
  );
}