import { Badge } from "@/components/ui/badge";

/**
 * Result-provenance label — answers "what KIND of number is this?" on every
 * performance-shaped figure (backtest PF, paper P&L, Monte Carlo projection,
 * model signal), the way the Trust Pane's live/static badges answer it for
 * data feeds. Ported from amo-arbitrage's honesty layer (ResultLabel).
 *
 * One shared component so the disclosure can never drift into different
 * phrasings per page (same rationale as RawRecordBadge). Uses only the
 * existing strict Badge variants — provenance is carried by the TEXT, with
 * the full explanation on the native title tooltip.
 */
export type ResultKind = "backtest" | "paper" | "live" | "simulated" | "signal";

const KIND_CONFIG: Record<
  ResultKind,
  { text: string; hint: string; variant: "neutral" | "info" | "warn" }
> = {
  backtest: {
    text: "Backtest",
    variant: "neutral",
    hint: "Historical simulation over past data. Not a live trade, not a promise of future performance.",
  },
  paper: {
    text: "Paper",
    variant: "info",
    hint: "Simulated forward-test trade. No live capital at risk.",
  },
  live: {
    text: "Live $",
    variant: "warn",
    hint: "Real-money result. (Live trading is disabled in the current phase — if you see this label, verify the source.)",
  },
  simulated: {
    text: "Simulated",
    variant: "warn",
    hint: "A statistical projection (e.g. Monte Carlo), not a historical record or a guarantee of future returns.",
  },
  signal: {
    text: "Signal",
    variant: "neutral",
    hint: "A model-generated recommendation, not a realized outcome or investment advice.",
  },
};

export function ResultLabel({
  kind,
  hint,
  className,
}: {
  kind: ResultKind;
  /** Override the default hint when page-specific context helps. */
  hint?: string;
  className?: string;
}) {
  const cfg = KIND_CONFIG[kind];
  return (
    <Badge
      variant={cfg.variant}
      title={hint ?? cfg.hint}
      className={`text-[10px] uppercase tracking-wide cursor-help ${className ?? ""}`}
      data-testid={`result-label-${kind}`}
    >
      {cfg.text}
    </Badge>
  );
}
