import { FlaskConical } from "lucide-react";
import Link from "next/link";

/**
 * Inline "Exploratory — not validated" banner, ported from amo-arbitrage's
 * honesty layer. Placed at the top of research surfaces (RL Lab, Edge
 * Research, Kairos, Polymarket, Hidden Pivots) so an exploratory signal feed
 * can never be mistaken for validated edge. One shared component so the
 * disclosure never drifts into per-page phrasings (same rationale as
 * RawRecordBadge / ResultLabel).
 */
export function ExploratoryBanner({
  what,
  className,
}: {
  /** e.g. "RL strategy discovery" — falls back to a generic phrase. */
  what?: string;
  className?: string;
}) {
  return (
    <div
      role="note"
      data-testid="exploratory-banner"
      className={`flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/5 px-4 py-2.5 text-xs text-warn ${
        className ?? ""
      }`}
    >
      <FlaskConical className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <span>
        <strong>Exploratory — not validated.</strong>{" "}
        {what ?? "This surface shows research under investigation"} and has not
        passed the validation gate (gate v2 + forward test). Do not treat it as
        validated edge. See{" "}
        <Link href="/validation" className="underline hover:text-foreground">
          Validation
        </Link>{" "}
        for what &ldquo;validated&rdquo; means and{" "}
        <Link href="/scorecard" className="underline hover:text-foreground">
          Scorecard
        </Link>{" "}
        for the live paper track record.
      </span>
    </div>
  );
}
