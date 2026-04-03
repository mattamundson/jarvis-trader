"use client";

export function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h3
        className="font-mono text-sm font-bold tracking-[0.15em] uppercase"
        style={{ color: "#00ff88" }}
      >
        {title}
      </h3>
      {subtitle && (
        <p className="font-mono text-[10px] mt-1" style={{ color: "#555" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
