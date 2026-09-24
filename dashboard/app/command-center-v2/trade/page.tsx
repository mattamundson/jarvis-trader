"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";

import { executionCapability, fetchControlPlaneSnapshot } from "@/lib/controlPlane";
import {
  buildTradeIntentIdempotencyKey,
  fetchManualTradeIntent,
  manualIntentCapability,
  previewManualTradeIntent,
  submitManualTradeIntent,
  type TradeIntentDirection,
  type TradeIntentOrderType,
  type TradeIntentResponse,
} from "@/lib/tradeIntent";

function n(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "SUBMITTED" || status === "PREVIEWED"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : status === "SUBMITTING"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-red-500/40 bg-red-500/10 text-red-300";
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}>{status}</span>;
}

export default function ManualTradeTicketPage() {
  const { data: snapshot, mutate } = useSWR(
    "command-center-v2-control-plane-trade",
    fetchControlPlaneSnapshot,
    { refreshInterval: 3000, revalidateOnFocus: true },
  );
  const capability = snapshot ? executionCapability(snapshot) : null;

  const [symbol, setSymbol] = useState("MES");
  const [direction, setDirection] = useState<TradeIntentDirection>("BUY");
  const [orderType, setOrderType] = useState<TradeIntentOrderType>("MARKET");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [riskPct, setRiskPct] = useState("0.50");
  const [requestedQty, setRequestedQty] = useState("");
  const [intent, setIntent] = useState<TradeIntentResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "submit" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submitCapability = useMemo(
    () => manualIntentCapability(intent, capability?.canApprovePaper === true),
    [intent, capability?.canApprovePaper],
  );

  function resetIntent() {
    setIntent(null);
    setMessage(null);
    setError(null);
  }

  async function handlePreview() {
    setBusy("preview");
    setError(null);
    setMessage(null);
    setIntent(null);
    try {
      const stop = n(stopLoss);
      const target = n(takeProfit);
      const riskPercent = n(riskPct);
      const qty = requestedQty.trim() ? n(requestedQty) : null;
      const limit = orderType === "LIMIT" ? n(limitPrice) : null;
      if (stop == null || stop <= 0) throw new Error("Enter a valid protective stop.");
      if (target == null || target <= 0) throw new Error("Enter a valid target.");
      if (riskPercent == null || riskPercent <= 0 || riskPercent > 1) {
        throw new Error("Risk must be greater than 0% and no more than 1.00%.");
      }
      if (orderType === "LIMIT" && (limit == null || limit <= 0)) {
        throw new Error("Enter a valid limit price.");
      }
      if (qty != null && (!Number.isInteger(qty) || qty < 1)) {
        throw new Error("Requested quantity must be a positive whole number.");
      }

      const result = await previewManualTradeIntent({
        idempotency_key: buildTradeIntentIdempotencyKey(),
        symbol: symbol.trim().toUpperCase(),
        direction,
        order_type: orderType,
        ...(orderType === "LIMIT" && limit != null ? { limit_price: limit } : {}),
        stop_loss: stop,
        take_profit: target,
        max_risk_fraction: riskPercent / 100,
        ...(qty != null ? { requested_quantity: qty } : {}),
        ttl_seconds: 60,
      });
      setIntent(result);
      setMessage(
        result.status === "PREVIEWED"
          ? "Preview created. Review the server-sized risk below before submitting."
          : result.terminal_reason || result.preview.blocking_reason || `Intent ${result.status}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleSubmit() {
    if (!intent || !submitCapability.canSubmit) return;
    setBusy("submit");
    setError(null);
    setMessage(null);
    try {
      const result = await submitManualTradeIntent(intent.intent_id);
      setIntent(result);
      await mutate();
      setMessage(
        result.status === "SUBMITTED"
          ? `Paper bracket acknowledged. Entry order ${result.order_id || "acknowledged"}.`
          : `Intent returned ${result.status}.`,
      );
    } catch (err) {
      // A transport/server error after broker submission may be ambiguous. Always
      // read the durable server state before deciding whether another click is safe.
      try {
        const resolved = await fetchManualTradeIntent(intent.intent_id);
        setIntent(resolved);
        if (resolved.status === "SUBMITTING") {
          setError("RECONCILIATION REQUIRED — DO NOT RETRY. Broker submission outcome is ambiguous.");
        } else {
          setError(
            resolved.terminal_reason ||
              (err instanceof Error ? err.message : String(err)),
          );
        }
      } catch {
        setError(
          "Submission failed and durable intent state could not be re-read. DO NOT RETRY until broker reconciliation is confirmed.",
        );
      }
    } finally {
      setBusy(null);
    }
  }

  const preview = intent?.preview;
  const cockpitBlocked = capability?.canApprovePaper !== true;

  return (
    <main className="min-h-screen bg-black px-5 py-6 text-zinc-100">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="border-b border-zinc-800 pb-5">
          <div className="text-xs font-semibold uppercase tracking-[0.25em] text-zinc-500">
            JARVIS Command Center V2 · RT-2
          </div>
          <div className="mt-1 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-semibold">Manual Paper Trade Intent</h1>
              <p className="mt-2 max-w-3xl text-sm text-zinc-400">
                The browser proposes geometry. JARVIS determines allowed size, rechecks fresh state, reconciles positions, and routes only protected futures brackets through SafetyLayer.
              </p>
            </div>
            <a href="/command-center-v2" className="text-sm font-semibold text-zinc-300 underline underline-offset-4">
              Back to cockpit
            </a>
          </div>
        </header>

        {cockpitBlocked ? (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
            <div className="font-semibold">Paper execution gate is blocked.</div>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {(capability?.reasons ?? ["control-plane state unavailable"]).map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm font-semibold text-red-300">
            {error}
          </div>
        ) : null}
        {message ? (
          <div className="rounded-lg border border-zinc-700 bg-zinc-950 p-4 text-sm text-zinc-300">{message}</div>
        ) : null}

        <section className="grid gap-5 lg:grid-cols-[1fr_0.9fr]">
          <form
            className="rounded-xl border border-zinc-800 bg-zinc-950 p-5"
            onSubmit={(event) => {
              event.preventDefault();
              void handlePreview();
            }}
          >
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">1 · Define intent</h2>
                <p className="mt-1 text-xs text-zinc-500">Futures only. Stop and target are mandatory.</p>
              </div>
              <span className="rounded-full border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400">PAPER ONLY</span>
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="text-sm text-zinc-400">
                Symbol
                <input value={symbol} onChange={(e) => { setSymbol(e.target.value); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
              </label>
              <label className="text-sm text-zinc-400">
                Direction
                <select value={direction} onChange={(e) => { setDirection(e.target.value as TradeIntentDirection); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100">
                  <option>BUY</option><option>SELL</option>
                </select>
              </label>
              <label className="text-sm text-zinc-400">
                Order type
                <select value={orderType} onChange={(e) => { setOrderType(e.target.value as TradeIntentOrderType); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100">
                  <option>MARKET</option><option>LIMIT</option>
                </select>
              </label>
              {orderType === "LIMIT" ? (
                <label className="text-sm text-zinc-400">
                  Limit price
                  <input type="number" step="any" value={limitPrice} onChange={(e) => { setLimitPrice(e.target.value); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
                </label>
              ) : <div />}
              <label className="text-sm text-zinc-400">
                Protective stop
                <input type="number" step="any" value={stopLoss} onChange={(e) => { setStopLoss(e.target.value); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
              </label>
              <label className="text-sm text-zinc-400">
                Target
                <input type="number" step="any" value={takeProfit} onChange={(e) => { setTakeProfit(e.target.value); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
              </label>
              <label className="text-sm text-zinc-400">
                Maximum account risk (%)
                <input type="number" min="0.01" max="1" step="0.01" value={riskPct} onChange={(e) => { setRiskPct(e.target.value); resetIntent(); }} className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
              </label>
              <label className="text-sm text-zinc-400">
                Quantity ceiling (optional)
                <input type="number" min="1" step="1" value={requestedQty} onChange={(e) => { setRequestedQty(e.target.value); resetIntent(); }} placeholder="Engine decides" className="mt-1 w-full rounded-md border border-zinc-700 bg-black px-3 py-2 text-zinc-100" />
              </label>
            </div>

            <button
              type="submit"
              disabled={busy != null || cockpitBlocked}
              className="mt-5 w-full rounded-md bg-zinc-100 px-4 py-3 text-sm font-bold text-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy === "preview" ? "Checking fresh state…" : "Preview server-sized trade"}
            </button>
          </form>

          <section className="rounded-xl border border-zinc-800 bg-zinc-950 p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">2 · Review & submit</h2>
                <p className="mt-1 text-xs text-zinc-500">Only the server preview shown here can be submitted.</p>
              </div>
              {intent ? <StatusPill status={intent.status} /> : null}
            </div>

            {!preview ? (
              <div className="mt-8 rounded-lg border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-600">
                Create a preview to calculate current entry, allowed size, dollar risk, and R:R.
              </div>
            ) : (
              <>
                <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <div className="text-zinc-500">Symbol</div><div className="text-right font-semibold">{preview.symbol}</div>
                  <div className="text-zinc-500">Direction</div><div className="text-right">{preview.direction}</div>
                  <div className="text-zinc-500">Server entry</div><div className="text-right">{preview.entry_price.toFixed(2)}</div>
                  <div className="text-zinc-500">Stop</div><div className="text-right">{preview.stop_loss.toFixed(2)}</div>
                  <div className="text-zinc-500">Target</div><div className="text-right">{preview.take_profit.toFixed(2)}</div>
                  <div className="text-zinc-500">Account equity</div><div className="text-right">{money(preview.account_equity)}</div>
                  <div className="text-zinc-500">Risk budget</div><div className="text-right">{money(preview.risk_budget_usd)}</div>
                  <div className="text-zinc-500">Risk / unit</div><div className="text-right">{money(preview.dollar_risk_per_unit)}</div>
                  <div className="text-zinc-500">Allowed quantity</div><div className={`text-right text-xl font-bold ${preview.final_quantity > 0 ? "text-emerald-300" : "text-red-300"}`}>{preview.final_quantity}</div>
                  <div className="text-zinc-500">Final dollar risk</div><div className="text-right font-semibold">{money(preview.final_dollar_risk)}</div>
                  <div className="text-zinc-500">Reward / risk</div><div className="text-right">{preview.reward_risk_ratio.toFixed(2)}R</div>
                </div>

                {submitCapability.requiresReconciliation ? (
                  <div className="mt-5 rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm font-bold text-red-300">
                    RECONCILIATION REQUIRED — DO NOT RETRY
                  </div>
                ) : null}

                {submitCapability.reasons.length > 0 && !submitCapability.canSubmit ? (
                  <ul className="mt-4 space-y-1 text-xs text-zinc-500">
                    {submitCapability.reasons.map((reason) => <li key={reason}>• {reason}</li>)}
                  </ul>
                ) : null}

                <button
                  type="button"
                  onClick={() => void handleSubmit()}
                  disabled={busy != null || !submitCapability.canSubmit}
                  className="mt-5 w-full rounded-md bg-emerald-400 px-4 py-3 text-sm font-black text-black disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-600"
                >
                  {busy === "submit" ? "Revalidating & submitting…" : "Submit protected paper bracket"}
                </button>
              </>
            )}
          </section>
        </section>

        <section className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-xs text-zinc-500">
          <span className="font-semibold text-zinc-300">Execution contract:</span> preview → fresh state → server sizing → human submit → fresh reconciliation → fresh risk/price checks → SafetyLayer → protected IB paper bracket. No browser-to-broker route and no automatic retry after an ambiguous submission.
        </section>
      </div>
    </main>
  );
}
