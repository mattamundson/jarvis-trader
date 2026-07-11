"use client";

// P2.3 IA readiness consolidation: the behavioral LLM tools (pattern analysis +
// formalize-an-observation) extracted from the retired /journal-review page. Mounted
// on /journal as the "Review" section; the honest metric grid moved to /performance.

import React, { useState } from "react";
import { Brain, Loader2, Sparkles } from "lucide-react";
import {
  analyzeJournalPatterns,
  formalizeInsight,
  type JournalFormalizeResult,
} from "@/lib/api";

function AnalysisMarkdown({ text }: { text: string }) {
  const sections = text.split(/^## /m).filter(Boolean);
  return (
    <div className="space-y-4">
      {sections.map((section, i) => {
        const [heading, ...body] = section.split("\n");
        return (
          <div key={i} className="border-l-2 border-neutral-700 pl-3">
            <div className="text-sm font-semibold text-neutral-200 mb-1">
              {heading.trim()}
            </div>
            <div className="text-sm text-neutral-400 whitespace-pre-wrap">
              {body.join("\n").trim()}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function JournalBehaviorView() {
  const [limit, setLimit] = useState(30);
  const [analysisText, setAnalysisText] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const [observation, setObservation] = useState("");
  const [formalized, setFormalized] = useState<JournalFormalizeResult | null>(null);
  const [formalizing, setFormalizing] = useState(false);
  const [formalizeError, setFormalizeError] = useState<string | null>(null);

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalysisText(null);
    try {
      const result = await analyzeJournalPatterns(limit);
      setAnalysisText(result.analysis);
    } catch (e) {
      setAnalyzeError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  async function runFormalize() {
    if (!observation.trim()) return;
    setFormalizing(true);
    setFormalizeError(null);
    setFormalized(null);
    try {
      const result = await formalizeInsight(observation);
      setFormalized(result);
    } catch (e) {
      setFormalizeError(e instanceof Error ? e.message : "Formalize failed");
    } finally {
      setFormalizing(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-neutral-100 flex items-center gap-2">
            <Brain className="h-5 w-5 text-violet-400" />
            Review
          </h2>
          <p className="text-xs text-neutral-500 mt-0.5">
            Koroush AK framework — behavioral patterns and falsifiable rules
          </p>
        </div>
        <div className="ml-auto">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="text-xs bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-300"
          >
            <option value={20}>Last 20 trades</option>
            <option value={30}>Last 30 trades</option>
            <option value={50}>Last 50 trades</option>
            <option value={100}>Last 100 trades</option>
          </select>
        </div>
      </div>

      {/* LLM Analysis */}
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-neutral-300 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-400" />
            Behavioral Pattern Analysis
          </h3>
          <button
            onClick={runAnalysis}
            disabled={analyzing}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
          >
            {analyzing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Brain className="h-3 w-3" />
            )}
            {analyzing ? "Analyzing…" : "Run Analysis"}
          </button>
        </div>

        {analyzeError && (
          <div className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded p-2">
            {analyzeError}
          </div>
        )}

        {!analysisText && !analyzing && !analyzeError && (
          <p className="text-xs text-neutral-600">
            Click Run Analysis to surface emotional patterns, trade duration stats, and one
            concrete rule from your last {limit} trades.
          </p>
        )}

        {analysisText && <AnalysisMarkdown text={analysisText} />}
      </div>

      {/* Formalize */}
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 space-y-3">
        <h3 className="text-sm font-medium text-neutral-300 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-cyan-400" />
          Formalize an Observation
        </h3>
        <p className="text-xs text-neutral-600">
          Turn a fuzzy pattern into a falsifiable rule with pass/fail thresholds.
        </p>
        <div className="flex gap-2">
          <input
            value={observation}
            onChange={(e) => setObservation(e.target.value)}
            placeholder="e.g. I win more on MES longs in bullish regimes"
            className="flex-1 text-sm bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-cyan-500/50"
          />
          <button
            onClick={runFormalize}
            disabled={formalizing || !observation.trim()}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors whitespace-nowrap"
          >
            {formalizing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            {formalizing ? "Formalizing…" : "Formalize"}
          </button>
        </div>

        {formalizeError && (
          <div className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded p-2">
            {formalizeError}
          </div>
        )}

        {formalized && (
          <div className="space-y-3 pt-1">
            <div className="rounded border border-neutral-700 bg-neutral-800/50 p-3 space-y-2 text-sm">
              <div>
                <span className="text-neutral-500 text-xs uppercase tracking-wide">
                  Pressure test
                </span>
                <p className="text-neutral-300 mt-0.5">{formalized.pressure_tested}</p>
              </div>
              <div>
                <span className="text-neutral-500 text-xs uppercase tracking-wide">Rule</span>
                <p className="text-cyan-300 font-medium mt-0.5">{formalized.falsifiable_rule}</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">Pass</span>
                  <p className="text-emerald-400 mt-0.5 text-xs">{formalized.pass_threshold}</p>
                </div>
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">Fail</span>
                  <p className="text-red-400 mt-0.5 text-xs">{formalized.fail_threshold}</p>
                </div>
              </div>
              {formalized.abandonment_criteria && (
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">
                    Abandon when
                  </span>
                  <p className="text-orange-300/80 mt-0.5 text-xs">
                    {formalized.abandonment_criteria}
                  </p>
                </div>
              )}
              {formalized.journal_columns.length > 0 && (
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">
                    Track columns
                  </span>
                  <div className="flex gap-1 flex-wrap mt-1">
                    {formalized.journal_columns.map((c) => (
                      <span
                        key={c}
                        className="text-xs px-1.5 py-0.5 rounded border border-neutral-600 bg-neutral-800 text-neutral-300"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="text-xs text-neutral-600">
                Sample size target: {formalized.sample_size} trades
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
