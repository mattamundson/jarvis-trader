"use client";

import React, { useState } from "react";
import {
  BookOpen,
  FlaskConical,
  ListChecks,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { MarketSessionStatusCard } from "@/components/MarketSessionStatusCard";
import { RecentTradesTableWidget } from "@/components/RecentTradesTableWidget";
import { useJournal, type CreateEntryPayload } from "@/hooks/useJournal";
import { OfflineFallback } from "@/components/OfflineFallback";

// ── Category badge colors ────────────────────────────────────────────────────

function getCatColor(cat: string): string {
  switch (cat) {
    case "CRITICAL": return "#ff4444";
    case "FINDING": return "#00ccff";
    case "IMPROVEMENT": return "#00ff88";
    case "VERDICT": return "#ffaa00";
    case "NOTE": return "#888";
    default: return "#888";
  }
}

// ── Static data (Hypothesis Tracker + Next Experiments remain static) ────────

type HypothesisResult = "Pending" | "In Progress" | "FAILED" | "No improvement" | "Partial (0.34)" | "No (WFE same 0.27)";

interface Hypothesis {
  hypothesis: string;
  prediction: string;
  tested: "Yes" | "No" | "Partial";
  result: HypothesisResult;
}

const HYPOTHESES: Hypothesis[] = [
  {
    hypothesis: "EMA trend gate prevents bear market losses",
    prediction: "WFE improvement",
    tested: "No",
    result: "Pending",
  },
  {
    hypothesis: "Regime_filter=OFF improves MGC daily WFE",
    prediction: "WFE >0.40",
    tested: "Partial",
    result: "In Progress",
  },
  {
    hypothesis: "Wider train window (12mo) improves MNQ WFE",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "No improvement",
  },
  {
    hypothesis: "Volume filter improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "FAILED",
  },
  {
    hypothesis: "MTF filter improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "No",
    result: "Pending",
  },
  {
    hypothesis: "Adaptive regime improves MGC 1d",
    prediction: "WFE >0.50",
    tested: "Yes",
    result: "No (WFE same 0.27)",
  },
  {
    hypothesis: "Adaptive regime improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "Partial (0.34)",
  },
];

interface Experiment {
  id: number;
  title: string;
  description: string;
}

const NEXT_EXPERIMENTS: Experiment[] = [
  {
    id: 1,
    title: "EMA 50/200 trend gate",
    description: "Prevent shorting during uptrend, longing during downtrend",
  },
  {
    id: 2,
    title: "MGC 1h vs 1d",
    description: "Intraday momentum may work better than daily macro",
  },
  {
    id: 3,
    title: "Multi-asset correlation",
    description: "Trade MNQ only when SPY trend aligns",
  },
  {
    id: 4,
    title: "Extend to 2020-2026 data",
    description: "COVID crash, full market cycles when data available",
  },
  {
    id: 5,
    title: "Different entry: RSI divergence vs STC crossover",
    description: "Compare RSI divergence signals against current STC-based entries",
  },
];

// ── Helper components ────────────────────────────────────────────────────────

function TestedBadge({ tested }: { tested: "Yes" | "No" | "Partial" }) {
  const styles = {
    Yes: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    No: "bg-neutral-500/15 text-neutral-500 border-neutral-500/30",
    Partial: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold ${styles[tested]}`}
    >
      {tested}
    </span>
  );
}

function ResultBadge({ result }: { result: HypothesisResult }) {
  let style = "text-neutral-500";
  if (result === "FAILED") style = "text-red-400 font-bold";
  else if (result === "In Progress") style = "text-cyan-400";
  else if (result === "Pending") style = "text-neutral-500";
  else if (result.startsWith("Partial")) style = "text-yellow-400";
  else if (result.startsWith("No")) style = "text-orange-400";

  return <span className={`font-mono text-xs ${style}`}>{result}</span>;
}

// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  icon,
  accentColor,
  children,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ReactNode;
  accentColor: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a]">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <div className="flex items-center gap-3">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg"
            style={{ backgroundColor: `${accentColor}15` }}
          >
            {icon}
          </div>
          <span
            className="font-mono text-xs font-bold tracking-[0.15em] uppercase"
            style={{ color: accentColor }}
          >
            {title}
          </span>
        </div>
        {open ? (
          <ChevronUp className="h-4 w-4 text-neutral-600" />
        ) : (
          <ChevronDown className="h-4 w-4 text-neutral-600" />
        )}
      </button>
      {open && (
        <div className="border-t border-[#1a1a2e] px-5 pb-5 pt-4">
          {children}
        </div>
      )}
    </div>
  );
}

// ── New Entry Form ────────────────────────────────────────────────────────────

function NewEntryForm({ onSubmit }: { onSubmit: (data: CreateEntryPayload) => Promise<void> }) {
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    category: "NOTE",
    status: "Active",
    entry: "",
    instrument: "",
    tags: "",
  });
  const [submitting, setSubmitting] = useState(false);

  return (
    <form
      className="rounded-lg border p-4 mb-4 space-y-3"
      style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e" }}
      onSubmit={async e => {
        e.preventDefault();
        setSubmitting(true);
        try {
          await onSubmit({
            date: form.date,
            category: form.category,
            status: form.status,
            entry: form.entry,
            instrument: form.instrument || undefined,
            tags: form.tags ? form.tags.split(",").map(t => t.trim()) : [],
          });
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider block mb-1" style={{ color: "#555" }}>Date</label>
          <input
            type="date"
            value={form.date}
            onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
            className="w-full text-xs font-mono rounded px-2 py-1.5 outline-none"
            style={{ backgroundColor: "#0a0a0a", border: "1px solid #2a2a45", color: "#e0e0e0" }}
          />
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider block mb-1" style={{ color: "#555" }}>Category</label>
          <select
            value={form.category}
            onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
            className="w-full text-xs font-mono rounded px-2 py-1.5 outline-none"
            style={{ backgroundColor: "#0a0a0a", border: "1px solid #2a2a45", color: "#e0e0e0" }}
          >
            {["NOTE", "FINDING", "IMPROVEMENT", "CRITICAL", "VERDICT"].map(c => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider block mb-1" style={{ color: "#555" }}>Instrument</label>
          <input
            type="text"
            placeholder="MCL, MNQ, MGC..."
            value={form.instrument}
            onChange={e => setForm(f => ({ ...f, instrument: e.target.value }))}
            className="w-full text-xs font-mono rounded px-2 py-1.5 outline-none"
            style={{ backgroundColor: "#0a0a0a", border: "1px solid #2a2a45", color: "#e0e0e0" }}
          />
        </div>
      </div>
      <div>
        <label className="text-[10px] font-mono uppercase tracking-wider block mb-1" style={{ color: "#555" }}>Entry</label>
        <textarea
          value={form.entry}
          onChange={e => setForm(f => ({ ...f, entry: e.target.value }))}
          required
          rows={3}
          placeholder="Research finding, observation, or decision..."
          className="w-full text-xs font-mono rounded px-2 py-1.5 outline-none resize-none"
          style={{ backgroundColor: "#0a0a0a", border: "1px solid #2a2a45", color: "#e0e0e0" }}
        />
      </div>
      <div className="flex items-center justify-between">
        <input
          type="text"
          placeholder="tags, comma, separated"
          value={form.tags}
          onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
          className="text-xs font-mono rounded px-2 py-1.5 outline-none w-48"
          style={{ backgroundColor: "#0a0a0a", border: "1px solid #2a2a45", color: "#e0e0e0" }}
        />
        <button
          type="submit"
          disabled={submitting || !form.entry}
          className="text-xs font-mono font-bold px-4 py-1.5 rounded transition-opacity disabled:opacity-40"
          style={{ backgroundColor: "#00ff8820", color: "#00ff88", border: "1px solid #00ff8840" }}
        >
          {submitting ? "Saving..." : "Save Entry"}
        </button>
      </div>
    </form>
  );
}

// ── Research Log Section ──────────────────────────────────────────────────────

const CATEGORIES = ["ALL", "CRITICAL", "FINDING", "IMPROVEMENT", "VERDICT", "NOTE"];
const STATUSES = ["ALL", "Active", "Resolved"];

function ResearchLogSection() {
  const [catFilter, setCatFilter] = useState<string>("ALL");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [showNewForm, setShowNewForm] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { entries, isOffline, createEntry, updateEntry } = useJournal({ limit: 100 });

  const filtered = entries.filter(e => {
    if (catFilter !== "ALL" && e.category !== catFilter) return false;
    if (statusFilter !== "ALL" && e.status !== statusFilter) return false;
    if (search && !e.entry.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-mono text-sm font-bold" style={{ color: "#00ff88" }}>Research Log</h3>
        <button
          onClick={() => setShowNewForm(!showNewForm)}
          className="text-[10px] font-mono px-2 py-1 rounded transition-colors"
          style={{ backgroundColor: "#00ff8810", color: "#00ff88", border: "1px solid #00ff8830" }}
        >
          {showNewForm ? "✕ Cancel" : "+ New Entry"}
        </button>
      </div>

      {/* New Entry Form */}
      {showNewForm && (
        <NewEntryForm
          onSubmit={async (data) => {
            await createEntry(data);
            setShowNewForm(false);
          }}
        />
      )}

      {/* Offline banner */}
      {isOffline && (
        <OfflineFallback variant="card" message="Engine offline — showing cached entries only" className="mb-3" />
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {/* Category pills */}
        <div className="flex items-center gap-1 flex-wrap">
          {CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => setCatFilter(cat)}
              className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors"
              style={{
                backgroundColor: catFilter === cat ? getCatColor(cat) + "20" : "#0d0d1a",
                color: catFilter === cat ? getCatColor(cat) : "#555",
                border: `1px solid ${catFilter === cat ? getCatColor(cat) + "40" : "#1a1a2e"}`,
              }}
            >{cat}</button>
          ))}
        </div>

        {/* Status pills */}
        <div className="flex items-center gap-1">
          {STATUSES.map(st => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors"
              style={{
                backgroundColor: statusFilter === st ? "#00d4ff20" : "#0d0d1a",
                color: statusFilter === st ? "#00d4ff" : "#555",
                border: `1px solid ${statusFilter === st ? "#00d4ff40" : "#1a1a2e"}`,
              }}
            >{st}</button>
          ))}
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search entries..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="text-xs font-mono rounded px-3 py-1.5 w-full max-w-xs outline-none"
          style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e", color: "#e0e0e0" }}
        />
      </div>

      {/* Entry list */}
      <div className="rounded-lg overflow-hidden" style={{ border: "1px solid #1a1a2e" }}>
        {filtered.length === 0 ? (
          <div className="p-6 text-center font-mono text-xs" style={{ color: "#555" }}>
            {entries.length === 0 ? "No entries yet — add your first research entry above" : "No entries match the current filters"}
          </div>
        ) : (
          filtered.map(entry => (
            <div
              key={entry.id}
              className="border-b cursor-pointer hover:bg-[#0d0d1a] transition-colors"
              style={{ borderColor: "#1a1a2e" }}
              onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
            >
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="text-[10px] font-mono shrink-0" style={{ color: "#555" }}>{entry.date}</span>
                <span
                  className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded shrink-0"
                  style={{ backgroundColor: getCatColor(entry.category) + "20", color: getCatColor(entry.category) }}
                >
                  {entry.category}
                </span>
                <span className="flex-1 text-xs font-mono truncate" style={{ color: "#e0e0e0" }}>{entry.entry}</span>
                {entry.instrument && (
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ backgroundColor: "#1a1a2e", color: "#888" }}
                  >{entry.instrument}</span>
                )}
                <span className="text-[10px] font-mono shrink-0" style={{ color: entry.status === "Active" ? "#00ff88" : "#555" }}>
                  {entry.status}
                </span>
              </div>
              {expandedId === entry.id && (
                <div className="px-4 pb-3 flex items-center justify-between" style={{ borderTop: "1px solid #1a1a2e" }}>
                  <p className="text-xs font-mono leading-relaxed flex-1 mr-4" style={{ color: "#888" }}>{entry.entry}</p>
                  <button
                    onClick={e => {
                      e.stopPropagation();
                      updateEntry(entry.id, { status: entry.status === "Active" ? "Resolved" : "Active" });
                    }}
                    className="text-[10px] font-mono px-2 py-1 rounded transition-colors shrink-0"
                    style={{ backgroundColor: "#1a1a2e", color: "#555", border: "1px solid #2a2a45" }}
                  >
                    {entry.status === "Active" ? "Mark Resolved" : "Reopen"}
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Summary stats */}
      <div className="mt-3 flex items-center gap-6 font-mono text-[10px] text-neutral-600">
        <span>{entries.filter(e => e.status === "Active").length} active</span>
        <span>{entries.filter(e => e.status === "Resolved").length} resolved</span>
        <span>{entries.length} total entries</span>
        {filtered.length !== entries.length && (
          <span style={{ color: "#00d4ff" }}>{filtered.length} shown</span>
        )}
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function JournalPage() {
  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* ── Market Session Status ──────────────────────────────────────────── */}
        <MarketSessionStatusCard />

        {/* ── Recent Trades ──────────────────────────────────────────────────── */}
        <RecentTradesTableWidget />

        {/* ── Section 1: Research Log (live from engine) ─────────────────────── */}
        <Section
          title="Research Log"
          icon={<BookOpen className="h-4 w-4 text-cyan-400" />}
          accentColor="#00d4ff"
        >
          <ResearchLogSection />
        </Section>

        {/* ── Section 2: Hypothesis Tracker ──────────────────────────────────── */}
        <Section
          title="Hypothesis Tracker"
          icon={<FlaskConical className="h-4 w-4 text-yellow-400" />}
          accentColor="#ffcc00"
        >
          <div className="overflow-x-auto">
            {/* Table header */}
            <div
              className="grid gap-3 pb-3 mb-1 font-mono text-[10px] uppercase tracking-wider"
              style={{
                gridTemplateColumns: "1fr 140px 80px 160px",
                color: "#555",
                borderBottom: "1px solid #1a1a2e",
              }}
            >
              <span>Hypothesis</span>
              <span className="text-center">Prediction</span>
              <span className="text-center">Tested</span>
              <span className="text-center">Result</span>
            </div>

            {/* Table rows */}
            {HYPOTHESES.map((h, i) => (
              <div
                key={i}
                className="grid gap-3 py-3 items-center font-mono text-xs"
                style={{
                  gridTemplateColumns: "1fr 140px 80px 160px",
                  borderBottom: "1px solid #111",
                }}
              >
                <span className="text-neutral-200 leading-relaxed">{h.hypothesis}</span>
                <span className="text-center text-neutral-400 tabular-nums">{h.prediction}</span>
                <span className="text-center">
                  <TestedBadge tested={h.tested} />
                </span>
                <span className="text-center">
                  <ResultBadge result={h.result} />
                </span>
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="mt-4 flex items-center gap-6 font-mono text-[10px] text-neutral-600">
            <span>{HYPOTHESES.filter(h => h.result === "Pending").length} pending</span>
            <span>{HYPOTHESES.filter(h => h.tested === "Yes").length} tested</span>
            <span>{HYPOTHESES.filter(h => h.result === "FAILED").length} failed</span>
          </div>
        </Section>

        {/* ── Section 3: Next Experiments ─────────────────────────────────────── */}
        <Section
          title="Next Experiments"
          icon={<ListChecks className="h-4 w-4 text-emerald-400" />}
          accentColor="#00ff88"
        >
          <div className="space-y-3">
            {NEXT_EXPERIMENTS.map(exp => (
              <div
                key={exp.id}
                className="flex items-start gap-4 rounded-lg border border-[#1a1a2e] bg-[#0d0d0d] px-4 py-3"
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-bold tabular-nums"
                  style={{
                    backgroundColor: "#00ff8815",
                    color: "#00ff88",
                    border: "1px solid #00ff8830",
                  }}
                >
                  {exp.id}
                </span>
                <div>
                  <p className="font-mono text-xs font-semibold text-neutral-200">{exp.title}</p>
                  <p className="font-mono text-[11px] text-neutral-500 mt-0.5 leading-relaxed">{exp.description}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Footer timestamp */}
        <div className="text-center font-mono text-[10px] text-neutral-700 py-4">
          JARVIS TRADER RESEARCH JOURNAL &middot; Live entries via engine API
        </div>
      </main>
    </div>
  );
}
