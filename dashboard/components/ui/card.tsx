import { cn } from "@/lib/utils";
import { PanelPullTime } from "@/components/ui/panel-pull-time";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-border bg-card text-card-foreground shadow-sm", className)}
      {...props}
    />
  );
}

type CardHeaderProps = React.HTMLAttributes<HTMLDivElement> & {
  /** When set, renders PanelPullTime under the header children (addition-only). */
  pulledAt?: Date | string | number | null;
  freshMs?: number;
  staleMs?: number;
};

export function CardHeader({ className, pulledAt, freshMs, staleMs, children, ...props }: CardHeaderProps) {
  return (
    <div className={cn("flex flex-col space-y-1.5 p-4", className)} {...props}>
      {children}
      {pulledAt !== undefined && (
        <PanelPullTime pulledAt={pulledAt} freshMs={freshMs} staleMs={staleMs} />
      )}
    </div>
  );
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-sm font-semibold uppercase tracking-wider text-muted-foreground", className)}
      {...props}
    />
  );
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4 pt-0", className)} {...props} />;
}
