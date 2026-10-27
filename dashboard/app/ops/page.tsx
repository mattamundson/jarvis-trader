import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { OpsView } from "@/components/ops/OpsView";
import { decideOpsAccess, readOpsAccessEnv } from "@/lib/ops/guard";
import { loadOpsSnapshot } from "@/lib/ops/read";

// Private: never prerendered or cached, never indexed. Basic Auth comes from middleware.ts (this path is not in
// isPublicReadOnlyPath); the guard below is the second lock for localhost-without-credentials and hosted deploys.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Ops · Hermes record (private)",
  description: "Private read-only view of the Hermes ladder, strike log, lockout and paper journal.",
  robots: { index: false, follow: false },
};

export default async function OpsPage() {
  const h = await headers();
  const decision = decideOpsAccess(readOpsAccessEnv(h.get("host")));
  if (!decision.allowed) notFound();
  return <OpsView snapshot={await loadOpsSnapshot()} />;
}
