/**
 * Status placeholder for the analysis-only tape surface.
 * Broker/account/process diagnostics are deliberately NOT initiated by page loads.
 * Unknown is amber, not failed/red and never readiness/green. Authoritative
 * operational status belongs to the separately permissioned status workflow.
 */
export async function readIbStatus() {
  return {
    ok: true,
    light: "amber" as const,
    probed: false,
    checkedAt: null,
    checks: [{
      name: "Broker readiness",
      ok: null,
      value: "Not checked by this analysis-only page; no broker or host probes performed",
    }],
  };
}
