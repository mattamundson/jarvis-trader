import { cn } from "@/lib/utils";

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral" | "live" | "static";

const variants: Record<BadgeVariant, string> = {
  bull: "bg-bull/15 text-bull border-bull/20",
  bear: "bg-bear/15 text-bear border-bear/20",
  warn: "bg-warn/15 text-warn border-warn/20",
  info: "bg-info/15 text-info border-info/20",
  neutral: "bg-muted text-muted-foreground border-border",
  // Data-provenance honesty badges (Trust Pane): `live` = freshly fetched from
  // a running interface; `static` = placeholder/stale/not-wired-to-live-data.
  live: "bg-bull/15 text-bull border-bull/20",
  static: "bg-muted text-muted-foreground border-border/60 border-dashed",
};

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ variant = "neutral", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
