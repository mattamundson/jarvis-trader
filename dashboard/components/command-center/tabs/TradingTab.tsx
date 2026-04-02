"use client";

import React, { useState } from "react";
import { PipelineFlowDiagram } from "@/components/command-center/PipelineFlowDiagram";
import type { SWRResponse } from "swr";
import {
  CheckCircle2,
  Circle,
  Trash2,
  RotateCcw,
  PlusCircle,
  AlertTriangle,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useLocalStorage } from "@/hooks/useLocalStorage";

// ── Local types ───────────────────────────────────────────────────────────

interface Trade {
  timestamp: string;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  pnl?: number;
  commission?: number;
}

interface SessionInfo {
  label: string;
  color: string;
  badge: string;
  isActive: boolean;
}

export interface CommandCenterData {
  session: SessionInfo;
  health: SWRResponse<unknown>;
  safety: SWRResponse<unknown>;
  portfolio: SWRResponse<unknown>;
  decisions: SWRResponse<unknown[]>;
  scheduler: SWRResponse<unknown>;
  macro: SWRResponse<unknown>;
  trades: SWRResponse<Trade[]>;
  refreshInterval: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtUSD(n: number | undefined | null): string {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

function pnlColor(n: number | undefined | null): string {
  if (n == null) return "text-gray-400";
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-gray-300";
}

// ── Checklist items definition ────────────────────────────────────────────

const CHECKLIST_ITEMS = [
  "Review overnight engine logs",
  "Verify IB Gateway connected (port 4002)",
  "Review agent decision queue",
  "Confirm kill switch DISENGAGED",
  "Check daily P&L vs -$500 limit",
  "Verify signal generation running",
  "Check consecutive loss counter",
] as const;

// ── MorningChecklist component ────────────────────────────────────────────

function MorningChecklist() {
  const [checked, setChecked] = useLocalStorage<boolean[]>(
    "jarvis-morning-checklist",
    Array(CHECKLIST_ITEMS.length).fill(false)
  );

  const completedCount = checked.filter(Boolean).length;
  const totalCount = CHECKLIST_ITEMS.length;
  const allComplete = completedCount === totalCount;
  const completionPct = Math.round((completedCount / totalCount) * 100);

  const toggle = (idx: number) => {
    setChecked((prev) => {
      const next = [...prev];
      next[idx] = !next[idx];
      return next;
    });
  };

  const reset = () => {
    setChecked(Array(CHECKLIST_ITEMS.length).fill(false));
  };

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40 h-full">
      <CardHeader className="pb-2 pt-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3" />
            MORNING CHECKLIST
          </CardTitle>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-400">
              <span className={cn(allComplete ? "text-green-400" : "text-cyan-400", "font-bold")}>
                {completedCount}
              </span>
              <span className="text-slate-600">/{totalCount}</span>
            </span>
            <Button
              onClick={reset}
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs font-mono text-slate-500 hover:text-cyan-400 hover:bg-slate-800/50 border border-slate-800 hover:border-cyan-900"
            >
              <RotateCcw className="w-2.5 h-2.5 mr-1" />
              RESET
            </Button>
          </div>
        </div>
        <Progress
          value={completionPct}
          className={cn(
            "h-1.5 bg-slate-800 mt-2",
            allComplete ? "[&>div]:bg-green-500" : "[&>div]:bg-cyan-500"
          )}
        />
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-1.5">
        {CHECKLIST_ITEMS.map((item, idx) => (
          <button
            key={idx}
            onClick={() => toggle(idx)}
            className={cn(
              "w-full flex items-center gap-2.5 px-3 py-2 rounded border text-left transition-all duration-150",
              checked[idx]
                ? "bg-green-950/40 border-green-900/50 hover:bg-green-950/60"
                : "bg-slate-800/30 border-slate-700/40 hover:bg-slate-800/50 hover:border-slate-600/60"
            )}
          >
            {checked[idx] ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
            ) : (
              <Circle className="w-3.5 h-3.5 text-slate-600 flex-shrink-0" />
            )}
            <span
              className={cn(
                "font-mono text-xs",
                checked[idx]
                  ? "text-green-400 line-through opacity-70"
                  : "text-slate-300"
              )}
            >
              {item}
            </span>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

// ── GoNoGoPanel component ─────────────────────────────────────────────────

function GoNoGoPanel() {
  const [checked] = useLocalStorage<boolean[]>(
    "jarvis-morning-checklist",
    Array(CHECKLIST_ITEMS.length).fill(false)
  );
  const [override, setOverride] = useLocalStorage<boolean>(
    "jarvis-gonogo-override",
    false
  );
  const [showOverrideInput, setShowOverrideInput] = useState(false);
  const [overrideText, setOverrideText] = useState("");

  const completedCount = checked.filter(Boolean).length;
  const allComplete = completedCount === CHECKLIST_ITEMS.length;
  const isGo = allComplete || override;

  const handleOverrideAttempt = () => {
    if (overrideText === "OVERRIDE") {
      setOverride(true);
      setShowOverrideInput(false);
      setOverrideText("");
    }
  };

  const handleClearOverride = () => {
    setOverride(false);
    setShowOverrideInput(false);
    setOverrideText("");
  };

  return (
    <Card
      className={cn(
        "bg-slate-900/60 border h-full",
        isGo
          ? override
            ? "border-red-700/70"
            : "border-green-700/70"
          : "border-yellow-700/50"
      )}
    >
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          {isGo ? (
            <ShieldCheck className="w-3 h-3 text-green-400" />
          ) : (
            <ShieldX className="w-3 h-3 text-yellow-400" />
          )}
          GO / NO-GO PANEL
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        {/* Main status display */}
        <div
          className={cn(
            "rounded border-2 p-4 text-center mb-4",
            override
              ? "border-red-600 bg-red-950/30"
              : isGo
              ? "border-green-600 bg-green-950/30"
              : "border-yellow-600 bg-yellow-950/30"
          )}
        >
          {override ? (
            <>
              <div className="font-mono text-2xl font-bold text-red-400 tracking-widest mb-1">
                MANUAL OVERRIDE ACTIVE
              </div>
              <div className="font-mono text-xs text-red-400/70">
                Override engaged — proceed with caution
              </div>
            </>
          ) : isGo ? (
            <>
              <div className="font-mono text-3xl font-bold text-green-400 tracking-widest mb-1">
                GO
              </div>
              <div className="font-mono text-xs text-green-400/70">
                ALL CLEAR — Ready to trade. All systems verified.
              </div>
            </>
          ) : (
            <>
              <div className="font-mono text-xl font-bold text-yellow-400 tracking-widest mb-1">
                HOLD — CHECKLIST INCOMPLETE
              </div>
              <div className="font-mono text-xs text-yellow-400/70">
                {completedCount}/{CHECKLIST_ITEMS.length} items complete — finish checklist before trading
              </div>
            </>
          )}
        </div>

        {/* Progress summary */}
        <div className="mb-4 space-y-1.5">
          <div className="flex justify-between text-xs font-mono text-slate-500">
            <span>Checklist completion</span>
            <span className={cn(allComplete ? "text-green-400" : "text-yellow-400")}>
              {completedCount}/{CHECKLIST_ITEMS.length}
            </span>
          </div>
          <Progress
            value={(completedCount / CHECKLIST_ITEMS.length) * 100}
            className={cn(
              "h-2 bg-slate-800",
              allComplete ? "[&>div]:bg-green-500" : "[&>div]:bg-yellow-500"
            )}
          />
        </div>

        {/* Override controls */}
        {!override ? (
          <>
            {!showOverrideInput ? (
              <Button
                onClick={() => setShowOverrideInput(true)}
                variant="ghost"
                className="w-full h-8 text-xs font-mono text-orange-400 hover:text-orange-300 border border-orange-900/50 hover:bg-orange-950/30 hover:border-orange-700"
              >
                <AlertTriangle className="w-3 h-3 mr-1.5" />
                MANUAL OVERRIDE
              </Button>
            ) : (
              <div className="space-y-2">
                <div className="font-mono text-xs text-orange-400 text-center">
                  Type <span className="font-bold text-white">OVERRIDE</span> to confirm
                </div>
                <input
                  type="text"
                  value={overrideText}
                  onChange={(e) => setOverrideText(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === "Enter" && handleOverrideAttempt()}
                  placeholder="Type OVERRIDE"
                  className="w-full bg-slate-800/60 border border-orange-800/50 rounded px-3 py-1.5 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-orange-600"
                />
                <div className="flex gap-2">
                  <Button
                    onClick={handleOverrideAttempt}
                    disabled={overrideText !== "OVERRIDE"}
                    className="flex-1 h-7 text-xs font-mono bg-orange-900 hover:bg-orange-800 border border-orange-700 text-orange-200 disabled:opacity-30"
                  >
                    CONFIRM
                  </Button>
                  <Button
                    onClick={() => { setShowOverrideInput(false); setOverrideText(""); }}
                    variant="ghost"
                    className="flex-1 h-7 text-xs font-mono text-slate-500 hover:text-slate-300 border border-slate-700"
                  >
                    CANCEL
                  </Button>
                </div>
              </div>
            )}
          </>
        ) : (
          <Button
            onClick={handleClearOverride}
            className="w-full h-8 text-xs font-mono bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white"
          >
            <RotateCcw className="w-3 h-3 mr-1.5" />
            CLEAR OVERRIDE
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ── RecentTradesTable component ───────────────────────────────────────────

function RecentTradesTable({ trades }: { trades?: Trade[] }) {
  const displayTrades = trades?.slice(0, 10) ?? [];
  const totalPnl = displayTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
          RECENT TRADES (LAST 10)
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        {displayTrades.length === 0 ? (
          <div className="text-xs text-slate-500 font-mono py-8 text-center">
            No trades recorded yet
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/60">
                    <th className="text-left pb-1.5 font-normal pr-2">Time</th>
                    <th className="text-left pb-1.5 font-normal pr-2">Sym</th>
                    <th className="text-left pb-1.5 font-normal pr-2">Side</th>
                    <th className="text-right pb-1.5 font-normal pr-2">Qty</th>
                    <th className="text-right pb-1.5 font-normal pr-2">Price</th>
                    <th className="text-right pb-1.5 font-normal">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {displayTrades.map((t, i) => (
                    <tr
                      key={i}
                      className="border-b border-slate-800/30 hover:bg-slate-800/20 transition-colors"
                    >
                      <td className="py-1 text-slate-500 pr-2 tabular-nums">
                        {fmtTime(t.timestamp)}
                      </td>
                      <td className="py-1 text-white font-bold pr-2">{t.symbol}</td>
                      <td className="py-1 pr-2">
                        <Badge
                          className={cn(
                            "text-xs font-mono py-0 px-1.5 border",
                            t.action === "BUY" || t.action === "LONG"
                              ? "bg-green-950 text-green-400 border-green-800"
                              : "bg-red-950 text-red-400 border-red-800"
                          )}
                        >
                          {t.action}
                        </Badge>
                      </td>
                      <td className="py-1 text-right text-slate-300 pr-2 tabular-nums">
                        {t.quantity}
                      </td>
                      <td className="py-1 text-right text-white pr-2 tabular-nums">
                        {t.price?.toFixed(2) ?? "—"}
                      </td>
                      <td className={cn("py-1 text-right tabular-nums", pnlColor(t.pnl))}>
                        {t.pnl != null ? fmtUSD(t.pnl) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Total P&L row */}
            <div className="mt-2 pt-2 border-t border-slate-700/60 flex justify-between items-center">
              <span className="font-mono text-xs text-slate-500">Total P&L (shown)</span>
              <span className={cn("font-mono text-sm font-bold tabular-nums", pnlColor(totalPnl))}>
                {fmtUSD(totalPnl)}
              </span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── SuccessCriteriaScorecard component ────────────────────────────────────

interface CriteriaValues {
  profitFactor: string;
  sharpeRatio: string;
  maxDrawdown: string;
  winRate: string;
}

type CriteriaKey = keyof CriteriaValues;

interface CriteriaConfig {
  key: CriteriaKey;
  label: string;
  target: string;
  placeholder: string;
  check: (v: number) => boolean;
  unit?: string;
}

const CRITERIA: CriteriaConfig[] = [
  {
    key: "profitFactor",
    label: "Profit Factor",
    target: "≥ 1.5",
    placeholder: "e.g. 1.8",
    check: (v) => v >= 1.5,
  },
  {
    key: "sharpeRatio",
    label: "Sharpe Ratio",
    target: "≥ 1.0",
    placeholder: "e.g. 1.2",
    check: (v) => v >= 1.0,
  },
  {
    key: "maxDrawdown",
    label: "Max Drawdown",
    target: "< 10%",
    placeholder: "e.g. 6.5",
    check: (v) => v <= 10,
    unit: "%",
  },
  {
    key: "winRate",
    label: "Win Rate",
    target: "≥ 45%",
    placeholder: "e.g. 52",
    check: (v) => v >= 45,
    unit: "%",
  },
];

function SuccessCriteriaScorecard() {
  const [values, setValues] = useLocalStorage<CriteriaValues>(
    "jarvis-success-criteria",
    { profitFactor: "", sharpeRatio: "", maxDrawdown: "", winRate: "" }
  );

  const updateField = (key: CriteriaKey, val: string) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const results = CRITERIA.map((c) => {
    const raw = values[c.key];
    if (raw === "" || raw == null) return "PENDING";
    const n = parseFloat(raw);
    if (isNaN(n)) return "PENDING";
    return c.check(n) ? "PASS" : "FAIL";
  });

  const overallStatus =
    results.every((r) => r === "PASS")
      ? "PASS"
      : results.some((r) => r === "FAIL")
      ? "FAIL"
      : "PENDING";

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-2 pt-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest">
            PAPER TRADING CRITERIA
          </CardTitle>
          <Badge
            className={cn(
              "text-xs font-mono py-0 px-2 border font-bold",
              overallStatus === "PASS"
                ? "bg-green-950 text-green-400 border-green-800"
                : overallStatus === "FAIL"
                ? "bg-red-950 text-red-400 border-red-800"
                : "bg-yellow-950 text-yellow-400 border-yellow-800"
            )}
          >
            {overallStatus}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <div className="grid grid-cols-2 gap-3">
          {CRITERIA.map((c, idx) => {
            const status = results[idx];
            return (
              <div
                key={c.key}
                className={cn(
                  "rounded border p-3 space-y-1.5",
                  status === "PASS"
                    ? "border-green-900/50 bg-green-950/20"
                    : status === "FAIL"
                    ? "border-red-900/50 bg-red-950/20"
                    : "border-slate-700/40 bg-slate-800/20"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-slate-400 uppercase tracking-wider">
                    {c.label}
                  </span>
                  <Badge
                    className={cn(
                      "text-xs font-mono py-0 px-1.5 border",
                      status === "PASS"
                        ? "bg-green-950 text-green-400 border-green-800"
                        : status === "FAIL"
                        ? "bg-red-950 text-red-400 border-red-800"
                        : "bg-slate-800 text-slate-500 border-slate-700"
                    )}
                  >
                    {status}
                  </Badge>
                </div>
                <div className="font-mono text-xs text-slate-600">
                  Target: <span className="text-slate-400">{c.target}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    step="0.01"
                    value={values[c.key]}
                    onChange={(e) => updateField(c.key, e.target.value)}
                    placeholder={c.placeholder}
                    className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-cyan-800 w-0"
                  />
                  {c.unit && (
                    <span className="font-mono text-xs text-slate-500">{c.unit}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ── DailyTradingLog component ─────────────────────────────────────────────

interface LogEntry {
  id: string;
  date: string;
  tradeCount: number;
  dailyPnl: number;
  notes: string;
}

const MAX_LOG_ENTRIES = 30;

function DailyTradingLog() {
  const todayStr = new Date().toISOString().split("T")[0];
  const [entries, setEntries] = useLocalStorage<LogEntry[]>(
    "jarvis-daily-log",
    []
  );
  const [form, setForm] = useState({
    date: todayStr,
    tradeCount: "",
    dailyPnl: "",
    notes: "",
  });

  const addEntry = () => {
    if (!form.date) return;
    const newEntry: LogEntry = {
      id: Date.now().toString(),
      date: form.date,
      tradeCount: parseInt(form.tradeCount) || 0,
      dailyPnl: parseFloat(form.dailyPnl) || 0,
      notes: form.notes,
    };
    setEntries((prev) => {
      const updated = [newEntry, ...prev];
      if (updated.length > MAX_LOG_ENTRIES) {
        return updated.slice(0, MAX_LOG_ENTRIES);
      }
      return updated;
    });
    setForm({ date: todayStr, tradeCount: "", dailyPnl: "", notes: "" });
  };

  const deleteEntry = (id: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  };

  const totalTrades = entries.reduce((sum, e) => sum + e.tradeCount, 0);
  const totalPnl = entries.reduce((sum, e) => sum + e.dailyPnl, 0);

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-2 pt-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <PlusCircle className="w-3 h-3" />
            DAILY TRADING LOG
          </CardTitle>
          <span className="font-mono text-xs text-slate-600">
            {entries.length}/{MAX_LOG_ENTRIES} entries
          </span>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-4">
        {/* Add entry form */}
        <div className="bg-slate-800/30 border border-slate-700/40 rounded p-3 space-y-3">
          <div className="grid grid-cols-4 gap-2">
            <div className="space-y-1">
              <label className="font-mono text-xs text-slate-500 uppercase tracking-wider">
                Date
              </label>
              <input
                type="date"
                value={form.date}
                onChange={(e) => setForm((p) => ({ ...p, date: e.target.value }))}
                className="w-full bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-800"
              />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-xs text-slate-500 uppercase tracking-wider">
                Trade Count
              </label>
              <input
                type="number"
                min="0"
                value={form.tradeCount}
                onChange={(e) => setForm((p) => ({ ...p, tradeCount: e.target.value }))}
                placeholder="0"
                className="w-full bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1.5 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-cyan-800"
              />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-xs text-slate-500 uppercase tracking-wider">
                Daily P&L ($)
              </label>
              <input
                type="number"
                step="0.01"
                value={form.dailyPnl}
                onChange={(e) => setForm((p) => ({ ...p, dailyPnl: e.target.value }))}
                placeholder="0.00"
                className="w-full bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1.5 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-cyan-800"
              />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-xs text-slate-500 uppercase tracking-wider invisible">
                Action
              </label>
              <Button
                onClick={addEntry}
                disabled={!form.date}
                className="w-full h-[30px] text-xs font-mono bg-cyan-950 hover:bg-cyan-900 border border-cyan-800 text-cyan-300 hover:text-cyan-200 disabled:opacity-30"
              >
                ADD ENTRY
              </Button>
            </div>
          </div>
          <div className="space-y-1">
            <label className="font-mono text-xs text-slate-500 uppercase tracking-wider">
              Notes
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
              placeholder="Market conditions, signal quality, observations..."
              rows={2}
              className="w-full bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1.5 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-cyan-800 resize-none"
            />
          </div>
        </div>

        {/* Log table */}
        {entries.length === 0 ? (
          <div className="text-xs text-slate-500 font-mono py-6 text-center">
            No daily log entries yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/60">
                  <th className="text-left pb-1.5 font-normal pr-3">Date</th>
                  <th className="text-right pb-1.5 font-normal pr-3">Trades</th>
                  <th className="text-right pb-1.5 font-normal pr-3">P&L</th>
                  <th className="text-left pb-1.5 font-normal pr-3">Notes</th>
                  <th className="text-right pb-1.5 font-normal w-8"></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr
                    key={entry.id}
                    className="border-b border-slate-800/30 hover:bg-slate-800/20 transition-colors"
                  >
                    <td className="py-1.5 text-white pr-3 tabular-nums">{entry.date}</td>
                    <td className="py-1.5 text-right text-slate-300 pr-3 tabular-nums">
                      {entry.tradeCount}
                    </td>
                    <td className={cn("py-1.5 text-right pr-3 tabular-nums", pnlColor(entry.dailyPnl))}>
                      {fmtUSD(entry.dailyPnl)}
                    </td>
                    <td className="py-1.5 text-slate-400 pr-3 max-w-[200px] truncate">
                      {entry.notes || "—"}
                    </td>
                    <td className="py-1.5 text-right">
                      <button
                        onClick={() => deleteEntry(entry.id)}
                        className="text-slate-600 hover:text-red-400 transition-colors"
                        title="Delete entry"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))}
                {/* Totals row */}
                <tr className="border-t-2 border-slate-700/60 bg-slate-800/30">
                  <td className="py-2 font-bold text-cyan-400 pr-3">
                    TOTALS ({entries.length} days)
                  </td>
                  <td className="py-2 text-right font-bold text-white pr-3 tabular-nums">
                    {totalTrades}
                  </td>
                  <td className={cn("py-2 text-right font-bold pr-3 tabular-nums", pnlColor(totalPnl))}>
                    {fmtUSD(totalPnl)}
                  </td>
                  <td className="py-2 text-slate-600 pr-3 text-xs">running totals</td>
                  <td></td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────

interface TradingTabProps {
  data: CommandCenterData;
}

export default function TradingTab({ data }: TradingTabProps) {
  const trades = data.trades.data;

  return (
    <div className="space-y-3 font-mono">
      {/* Section A — Checklist + Go/No-Go */}
      <div className="grid grid-cols-2 gap-3">
        <MorningChecklist />
        <GoNoGoPanel />
      </div>

      {/* Section B — Recent Trades + Success Criteria */}
      <div className="grid grid-cols-2 gap-3">
        <RecentTradesTable trades={trades} />
        <SuccessCriteriaScorecard />
      </div>

      {/* Section C — Daily Log (full width) */}
      <DailyTradingLog />

      {/* Section D — Pipeline Flow Diagram (full width) */}
      <PipelineFlowDiagram latestRun={null} />
    </div>
  );
}
