// Item 2: canonical source labels for every /tape panel.
export const SOURCE_LABELS = {
  ibPaper: "IB paper 4002",
  ibLive: "IB live read-only 4001",
  yahoo: "Yahoo delayed",
  databento: "Databento backfill",
  snapshot: "Published snapshot",
} as const;

export function labelForPort(port: unknown): string | null {
  const p = Number(port);
  if (p === 4002) return SOURCE_LABELS.ibPaper;
  if (p === 4001) return SOURCE_LABELS.ibLive;
  return null;
}

export function normalizeSource(raw: unknown, port?: unknown): string {
  const s = typeof raw === "string" ? raw.toLowerCase() : "";
  if (s.includes("databento")) return SOURCE_LABELS.databento;
  if (s.includes("yahoo")) return SOURCE_LABELS.yahoo;
  if (s.includes("4002") || s.includes("paper")) return SOURCE_LABELS.ibPaper;
  if (s.includes("4001") || s.includes("live")) return SOURCE_LABELS.ibLive;
  return labelForPort(port) ?? (typeof raw === "string" && raw ? raw : "unknown");
}
