export interface HermesGatesReport {
  found: boolean;
  gates: { name: string; status: "pass" | "fail" | "unknown" }[];
  fileLockout: boolean | null;
  message: string;
}

/** No committed gate-source contract exists. Never manufacture a passing report. */
export function unavailableHermesGates(): HermesGatesReport {
  return {
    found: false,
    gates: [],
    fileLockout: null,
    message: "Hermes gates unavailable: no gate data source is configured.",
  };
}
