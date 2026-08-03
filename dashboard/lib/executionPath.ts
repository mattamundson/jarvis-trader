/**
 * Execution-path honesty layer — single source of truth for "can an order
 * actually reach a broker" across every dashboard surface.
 *
 * THE BUG (D3-01)
 * ----------------
 * Every execution-status badge on the dashboard (8+ mounted components) has
 * been rendering green "CONNECTED" from `ibkr_execution_connected` (and its
 * cousin `execution_connected_verified`). Both booleans are cached connector
 * flags — they go true the moment the IBKR TCP socket to the paper Gateway is
 * up, regardless of whether the order path itself is real. The engine's own
 * `/health` response ALSO carries an honest `execution_path` probe
 * (`{ simulated, broker_ack, detail }`) that can simultaneously report
 * `simulated: true, broker_ack: false` — i.e. "IBGatewayConnector holds no
 * ib_insync handle, orders are simulated in-process and never reach a
 * broker" — while both legacy booleans still read `true`. No dashboard file
 * read `execution_path` before this fix (`git grep execution_path -- dashboard`
 * was 0 matches), so an operator doing a pre-trade check saw a "verified"
 * green broker connection when no order could ever reach a broker. See memory
 * `project_jarvis_order_path_is_simulator_2026_07_21`.
 *
 * THE CONTRACT
 * ------------
 * Any panel that renders execution/broker connectivity MUST derive its
 * label/tone/color through `executionStatus()`, never by reading
 * `ibkr_execution_connected` / `execution_connected_verified` directly. This
 * is a dashboard-only fix: `execution_path` already survives the dashboard's
 * engine proxy byte-identical to the engine's own `/health` (rung 4,
 * confirmed live) — no engine change, no new endpoint. The engine-side
 * booleans themselves are NOT made honest here (10+ non-dashboard consumers —
 * health_watchdog.py, tests, ops dashboards, the MCP server — key off
 * `ibkr_execution_connected == true`; flipping it is a separate, higher
 * blast-radius finding).
 *
 * RESOLUTION ORDER (load-bearing — see executionStatus below):
 *   1. no health data                                -> unknown
 *   2. execution_path.simulated === true             -> simulated (never green)
 *   3. execution_path.broker_ack === true             -> connected (the ONLY green state)
 *   4. execution_path.simulated === false, no ack      -> degraded ("no broker ack")
 *   5. no execution_path probe, legacy flag truthy    -> unprobed (amber, NOT bare "CONNECTED")
 *   6. ib_execution_stale === true                    -> stale
 *   7. otherwise                                       -> disconnected
 *
 * `brokerReachable` is computed once, directly from `execution_path.broker_ack
 * === true`, independent of which state/label branch matched. This keeps the
 * safety invariant (`brokerReachable === (execution_path?.broker_ack ===
 * true)`, and therefore "never true unless the broker actually acknowledged")
 * true unconditionally, even for a pathological/self-contradictory payload —
 * a defensive property that must hold no matter which display branch a future
 * edit adds.
 */

/** The engine's honest execution-path probe (mirrors engine's ExecutionPathProbe). */
export interface ExecutionPathProbe {
  class_name?: string | null;
  simulated?: boolean | null;
  broker_ack?: boolean | null;
  detail?: string | null;
}

/** The subset of a /health-shaped payload this module reads. */
export interface ExecutionHealthFields {
  ibkr_connected?: boolean | null;
  ibkr_execution_connected?: boolean | null;
  execution_connected_verified?: boolean | null;
  ib_execution_stale?: boolean | null;
  execution_path?: ExecutionPathProbe | null;
}

export type ExecutionState =
  | "unknown"
  | "simulated"
  | "stale"
  | "connected"
  | "degraded"
  | "unprobed"
  | "disconnected";

export type ExecutionTone = "bull" | "warn" | "bear" | "neutral";

export interface ExecutionStatus {
  state: ExecutionState;
  label: string;
  tone: ExecutionTone;
  /** True ONLY when execution_path.broker_ack === true. Never re-derive this
   *  from ibkr_execution_connected / execution_connected_verified. */
  brokerReachable: boolean;
  detail: string;
}

/**
 * Classify a /health-shaped payload into a display-ready execution status.
 * Pure and deterministic; never throws, even on null/undefined input.
 */
export function executionStatus(
  h: ExecutionHealthFields | null | undefined,
): ExecutionStatus {
  const probe = h?.execution_path ?? null;
  // Computed independently of the branch below — see module docblock.
  const brokerReachable = probe?.broker_ack === true;

  // 1. No health data at all.
  if (h == null) {
    return {
      state: "unknown",
      label: "EXEC ?",
      tone: "neutral",
      brokerReachable,
      detail: "No health data available.",
    };
  }

  // 2. The honest probe says orders are simulated in-process. This must win
  //    even when the legacy connector booleans read true — that's the exact
  //    regression this module exists to fix.
  if (probe?.simulated === true) {
    return {
      state: "simulated",
      label: "SIMULATED",
      tone: "warn",
      brokerReachable,
      detail:
        probe.detail ??
        "Orders are simulated in-process and never reach a broker.",
    };
  }

  // 3. The only state that may ever render as a bare, green "CONNECTED".
  if (probe?.broker_ack === true) {
    return {
      state: "connected",
      label: "CONNECTED",
      tone: "bull",
      brokerReachable,
      detail: probe.detail ?? "Broker acknowledged the execution path.",
    };
  }

  // 4. Real (non-simulated) connector, but the broker hasn't ack'd anything yet.
  if (probe?.simulated === false) {
    return {
      state: "degraded",
      label: "NO BROKER ACK",
      tone: "warn",
      brokerReachable,
      detail:
        probe.detail ??
        "Execution connector is live but the broker has not acknowledged an order.",
    };
  }

  // 5. Older engine build with no execution_path probe at all — fall back to
  //    the legacy cached flags, but label it "unprobed" (amber), never a bare
  //    "CONNECTED" — that would re-introduce the exact lie this fixes.
  if (probe == null) {
    const legacyConnected =
      h.execution_connected_verified ??
      h.ibkr_execution_connected ??
      h.ibkr_connected;
    if (legacyConnected) {
      return {
        state: "unprobed",
        label: "CONNECTED (UNPROBED)",
        tone: "warn",
        brokerReachable,
        detail:
          "Older engine build — no execution_path probe available; cached connector flags are unverified.",
      };
    }
  }

  // 6. Explicitly stale.
  if (h.ib_execution_stale === true) {
    return {
      state: "stale",
      label: "STALE",
      tone: "bear",
      brokerReachable,
      detail: "Execution connector state is stale.",
    };
  }

  // 7. Everything else — honestly disconnected.
  return {
    state: "disconnected",
    label: "DISCONNECTED",
    tone: "bear",
    brokerReachable,
    detail: "Execution path is disconnected.",
  };
}
