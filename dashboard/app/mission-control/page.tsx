import { isVercelDeployment } from "@/lib/operatorMode";

export const dynamic = "force-dynamic";

/**
 * Local Mission Control keeps positions and P&L.
 * A Vercel runtime (VERCEL=1) renders gates and lockout only.
 */
export default async function MissionControlPage() {
  if (isVercelDeployment()) {
    const { VercelGatesOnly } = await import("./VercelGatesOnly");
    return <VercelGatesOnly />;
  }
  const { MissionControlLocal } = await import("./MissionControlLocal");
  return <MissionControlLocal />;
}
