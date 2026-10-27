import type { ReactNode } from "react";

export const MONO = "font-mono tabular-nums";

export function Panel({ title, right, children, testId, className = "" }: { title: string; right?: ReactNode; children: ReactNode; testId?: string; className?: string }) {
  return (
    <section data-testid={testId} className={`rounded border border-border bg-card/60 ${className}`}>
      <header className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Pill({ tone, children }: { tone: "bull" | "bear" | "warn" | "muted"; children: ReactNode }) {
  const cls = { bull: "text-bull border-bull/50", bear: "text-bear border-bear/50", warn: "text-warn border-warn/50", muted: "text-muted-foreground border-border" }[tone];
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>{children}</span>;
}

export function Stat({ label, value, sub, tone = "muted" }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "bull" | "bear" | "warn" | "muted" }) {
  const cls = { bull: "text-bull", bear: "text-bear", warn: "text-warn", muted: "text-foreground" }[tone];
  return (
    <div className="rounded border border-border px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-2xl font-semibold ${MONO} ${cls}`}>{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

export function Missing({ what }: { what: string }) {
  return <p className="text-xs text-warn">Not found in the record: {what}. Showing nothing rather than guessing.</p>;
}
