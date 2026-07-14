import { Badge } from "@/components/ui/badge";

/**
 * Canonical "this surface shows the raw (un-deduped) record" disclosure.
 *
 * Use this on ANY widget that displays raw over-counted engine numbers that
 * cannot be deduplicated (regime, per-account, exit-reason, commission). One
 * shared component means the disclosure can never silently go missing or drift
 * into a different phrasing on a new raw surface — the whole point of the honest
 * migration is that every raw surface is visibly flagged.
 */
export function RawRecordBadge({ className }: { className?: string }) {
  return (
    <Badge variant="warn" className={className}>
      Raw record · not deduped
    </Badge>
  );
}
