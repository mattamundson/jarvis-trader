import type { ReactNode } from "react";

/** Avoid static prerender for WS-heavy trade routes (build-time webpack/runtime issues). */
export const dynamic = "force-dynamic";

export default function TradesLayout({ children }: { children: ReactNode }) {
  return children;
}
