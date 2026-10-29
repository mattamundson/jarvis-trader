import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { OpsView } from "@/components/ops/OpsView";
import { decideOpsAccess, readOpsAccessEnv } from "@/lib/ops/guard";
import { loadOpsSnapshot } from "@/lib/ops/read";

// Public read-only record; never prerendered or cached. Missing local records remain unavailable.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Ops · Hermes record (read-only)",
  description: "Public read-only view of the Hermes ladder, strike log, lockout and paper journal.",
  robots: { index: false, follow: false },
};

export default async function OpsPage() {
  const h = await headers();
  const decision = decideOpsAccess(readOpsAccessEnv(h.get("host")));
  if (!decision.allowed) notFound();
  return <OpsView snapshot={await loadOpsSnapshot()} />;
}
