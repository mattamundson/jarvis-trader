"use client";

import { useCallback } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { WsEvent } from "@/hooks/ws-types";
import { useToast } from "@/lib/toast-context";

/** Subscribes to engine WebSocket and surfaces pending-approval queue events app-wide. */
export function PendingApprovalToastListener() {
  const { addToast } = useToast();

  const onEvent = useCallback(
    (event: WsEvent) => {
      if (event.type !== "pending_approval_created") return;
      const qty =
        typeof event.quantity === "number" ? ` ×${event.quantity}` : "";
      const sym = event.symbol ?? "?";
      const act = event.final_action ?? "?";
      addToast(
        `Approval required: ${sym} ${String(act).toUpperCase()}${qty} — open Pending Approvals`,
        "warning",
      );
    },
    [addToast],
  );

  useWebSocket(undefined, onEvent);

  return null;
}
