"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { X, CheckCircle, XCircle, AlertTriangle, BookOpen } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

interface TradeDetail {
  trade_id: string;
  symbol: string;
  side?: string;
  action?: string;
  quantity?: number;
  entry_price?: number;
  exit_price?: number | null;
  pnl?: number | null;
  entry_time?: string;
  exit_time?: string | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  strategy_params?: string | null;
}

interface ReviewDetail {
  grade?: string | null;
  setup_quality?: string | null;
  strengths?: string[];
  weaknesses?: string[];
  rule_violations?: string[];
  lessons?: string | null;
  improvement_tags?: string[];
  llm_model?: string | null;
  review_status: string;
  pnl_usd?: number | null;
  pnl_pct?: number | null;
  hold_minutes?: number | null;
  rr_ratio?: number | null;
  actual_r?: number | null;
  regime?: string | null;
  conviction?: number | null;
  bull_score?: number | null;
  bear_score?: number | null;
  pipeline_summary?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

interface TradeWithReviewResponse {
  trade: TradeDetail;
  review: ReviewDetail | null;
}

const GRADE_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  A: { bg: "bg-emerald-500/20", text: "text-emerald-400", label: "Excellent" },
  B: { bg: "bg-teal-500/20", text: "text-teal-400", label: "Good" },
  C: { bg: "bg-yellow-500/20", text: "text-yellow-400", label: "Average" },
  D: { bg: "bg-orange-500/20", text: "text-orange-400", label: "Poor" },
  F: { bg: "bg-red-500/20", text: "text-red-400", label: "Fail" },
};

function holdStr(minutes: number | null | undefined): string {
  if (!minutes) return "—";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

export function TradeReviewPanel({
  tradeId,
  onClose,
}: {
  tradeId: string;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useSWR<TradeWithReviewResponse>(
    `/trades/${tradeId}/review`,
    fetcher,
    { refreshInterval: POLL_INTERVAL.STATUS }
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
        <div className="h-3 w-3 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        Loading review…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-between py-3">
        <span className="text-xs text-bear">Failed to load review.</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  const { trade, review } = data;
  const direction = trade.action || trade.side || "—";
  const pnl = trade.pnl ?? null;
  const pnlColor = pnl == null ? "" : pnl > 0 ? "text-bull" : pnl < 0 ? "text-bear" : "";
  const grade = review?.grade ?? null;
  const gradeStyle = grade ? GRADE_COLORS[grade] : null;

  // Parse strategy_params for entry context
  let params: Record<string, unknown> = {};
  try {
    if (typeof trade.strategy_params === "string" && trade.strategy_params) {
      params = JSON.parse(trade.strategy_params);
    }
  } catch {
    // ignore
  }

  const regime = review?.regime ?? (params.regime as string | undefined) ?? null;
  const conviction = review?.conviction ?? (params.conviction as number | undefined) ?? null;
  const bullScore = review?.bull_score ?? (params.bull_score as number | undefined) ?? null;
  const bearScore = review?.bear_score ?? (params.bear_score as number | undefined) ?? null;
  const pipelineSummary = review?.pipeline_summary ?? (params.summary as string | undefined) ?? null;

  return (
    <div className="rounded-lg border border-border bg-card/50 p-4 text-xs space-y-4">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono font-bold text-sm text-foreground">
            {trade.symbol} {direction.toUpperCase()}
          </span>
          {trade.entry_price != null && (
            <span className="text-muted-foreground font-mono">
              {formatCurrency(trade.entry_price)}
              {trade.exit_price != null && ` → ${formatCurrency(trade.exit_price)}`}
            </span>
          )}
          {pnl != null && (
            <span className={`font-semibold font-mono ${pnlColor}`}>
              {pnl >= 0 ? "+" : ""}
              {formatCurrency(pnl)}
              {review?.pnl_pct != null && (
                <span className="ml-1 text-[10px] opacity-70">
                  ({review.pnl_pct >= 0 ? "+" : ""}
                  {review.pnl_pct.toFixed(1)}%)
                </span>
              )}
            </span>
          )}
          {gradeStyle && grade ? (
            <span
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-bold ${gradeStyle.bg} ${gradeStyle.text}`}
            >
              {grade}
              <span className="font-normal text-[10px]">{gradeStyle.label}</span>
            </span>
          ) : review?.review_status === "pending" ? (
            <span className="text-muted-foreground italic">Analyzing…</span>
          ) : null}
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground shrink-0"
          aria-label="Close review"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
        {review?.hold_minutes != null && (
          <span>Hold: <span className="text-foreground">{holdStr(review.hold_minutes)}</span></span>
        )}
        {regime && (
          <span>Regime: <span className="text-foreground">{regime}</span></span>
        )}
        {conviction != null && (
          <span>Conviction: <span className="text-foreground">{conviction}/10</span></span>
        )}
        {review?.rr_ratio != null && (
          <span>R:R: <span className="text-foreground">{review.rr_ratio.toFixed(1)}:1</span></span>
        )}
        {review?.actual_r != null && (
          <span>
            Actual R:{" "}
            <span className={review.actual_r >= 0 ? "text-bull" : "text-bear"}>
              {review.actual_r >= 0 ? "+" : ""}
              {review.actual_r.toFixed(2)}R
            </span>
          </span>
        )}
        {review?.setup_quality && (
          <span>
            Setup:{" "}
            <span className="text-foreground capitalize">{review.setup_quality}</span>
          </span>
        )}
      </div>

      {/* Debate scores */}
      {(bullScore != null || bearScore != null) && (
        <div className="flex gap-4">
          {bullScore != null && (
            <span className="text-bull">Bull {bullScore.toFixed(1)}/10</span>
          )}
          {bearScore != null && (
            <span className="text-bear">Bear {bearScore.toFixed(1)}/10</span>
          )}
        </div>
      )}

      {/* Pipeline summary */}
      {pipelineSummary && (
        <p className="text-muted-foreground italic border-l-2 border-accent pl-3">
          &ldquo;{pipelineSummary}&rdquo;
        </p>
      )}

      {/* Risk plan */}
      {(trade.stop_loss != null || trade.take_profit != null) && (
        <div className="flex gap-4 text-muted-foreground">
          {trade.stop_loss != null && (
            <span>Stop: <span className="text-foreground font-mono">{formatCurrency(trade.stop_loss)}</span></span>
          )}
          {trade.take_profit != null && (
            <span>Target: <span className="text-foreground font-mono">{formatCurrency(trade.take_profit)}</span></span>
          )}
        </div>
      )}

      {review && review.review_status === "complete" && (
        <>
          {/* Strengths */}
          {review.strengths && review.strengths.length > 0 && (
            <div>
              <p className="text-muted-foreground uppercase tracking-wider text-[10px] font-semibold mb-1.5">
                Strengths
              </p>
              <ul className="space-y-0.5">
                {review.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <CheckCircle className="h-3 w-3 text-bull mt-0.5 shrink-0" />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Weaknesses */}
          {review.weaknesses && review.weaknesses.length > 0 && (
            <div>
              <p className="text-muted-foreground uppercase tracking-wider text-[10px] font-semibold mb-1.5">
                Weaknesses
              </p>
              <ul className="space-y-0.5">
                {review.weaknesses.map((w, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <XCircle className="h-3 w-3 text-bear mt-0.5 shrink-0" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Rule violations */}
          {review.rule_violations && review.rule_violations.length > 0 && (
            <div>
              <p className="text-muted-foreground uppercase tracking-wider text-[10px] font-semibold mb-1.5">
                Rule Violations
              </p>
              <ul className="space-y-0.5">
                {review.rule_violations.map((v, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <AlertTriangle className="h-3 w-3 text-orange-400 mt-0.5 shrink-0" />
                    <span className="text-orange-400">{v}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Lesson */}
          {review.lessons && (
            <div className="rounded-md bg-accent/5 border border-accent/20 p-3">
              <p className="flex items-center gap-1.5 text-muted-foreground uppercase tracking-wider text-[10px] font-semibold mb-2">
                <BookOpen className="h-3 w-3" />
                Lesson
              </p>
              <p className="text-foreground leading-relaxed">{review.lessons}</p>
            </div>
          )}

          {/* Improvement tags */}
          {review.improvement_tags && review.improvement_tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {review.improvement_tags.map((tag, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded-full bg-muted/50 text-muted-foreground text-[10px] font-mono"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      {review?.review_status === "pending" && (
        <div className="text-muted-foreground italic text-center py-2">
          LLM analysis in progress — refreshes automatically…
        </div>
      )}

      {review?.review_status === "failed" && (
        <div className="text-bear italic">
          {review.lessons || "Analysis failed — try regenerating."}
        </div>
      )}
    </div>
  );
}
