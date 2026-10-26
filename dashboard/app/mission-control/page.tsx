import { isVercelDeployment } from "@/lib/operatorMode";

/**
 * VERCEL is inlined at build time. The local branch is the port 3010
 * scoreboard. The Vercel branch renders gates and lockout only, and does
 * not import the position or P&L panels.
 */
export default async function MissionControlPage() {
  if (isVercelDeployment()) {
    const { VercelGatesOnly } = await import("./VercelGatesOnly");
    return <VercelGatesOnly />;
  }
  const { MissionControlLocal } = await import("./MissionControlLocal");
  return <MissionControlLocal />;
}
