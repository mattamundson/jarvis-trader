import { Badge } from "@/components/ui/badge";
import { classifyFreshness, type FreshnessConfig } from "@/lib/freshness";
import { cn } from "@/lib/utils";

interface DataFreshnessProps extends FreshnessConfig {
  className?: string;
}

export function DataFreshness({
  source,
  dataTimestamp,
  isFixture,
  stalenessThresholdMs,
  className,
}: DataFreshnessProps) {
  const freshness = classifyFreshness({
    source,
    dataTimestamp,
    isFixture,
    stalenessThresholdMs,
  });

  const variantMap = {
    LIVE: "bull" as const,
    DELAYED: "warn" as const,
    STALE: "bear" as const,
    SAMPLE_DATA: "static" as const,
  };

  const variant = variantMap[freshness.state];

  return (
    <div className={cn("inline-flex items-center gap-2 text-xs font-mono", className)}>
      <Badge variant={variant} className="uppercase">
        {freshness.state === "SAMPLE_DATA"
          ? "SAMPLE DATA"
          : freshness.state === "LIVE"
            ? "● LIVE"
            : freshness.state}
      </Badge>
      <span className="text-slate-500">
        {source} · {freshness.asOfCT}
        {freshness.state !== "SAMPLE_DATA" &&
          freshness.state !== "LIVE" &&
          ` (${freshness.ageSeconds}s)`}
      </span>
    </div>
  );
}
