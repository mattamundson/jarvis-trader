import type { Metadata } from "next";
import { TapeView } from "@/components/tape/TapeView";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "TAPE · order flow",
  description: "Read-only ES order-flow tape. No positions, no P&L, not a signal.",
};

export default function TapePage() {
  return <TapeView />;
}
