/** Engine `/ws/events` message shapes (flattened after JSON parse). */

export type WsEvent =
  | { type: "price_update"; symbol: string; price: number; timestamp?: string }
  | {
      type: "pipeline_complete";
      symbol: string;
      action: string;
      confidence: number;
      timestamp?: string;
    }
  | { type: "kill_switch"; active: boolean; timestamp?: string }
  | { type: "circuit_breaker"; reason: string; timestamp?: string }
  | {
      type: "order_fill";
      symbol: string;
      action: string;
      price: number;
      quantity: number;
      timestamp?: string;
    }
  | { type: "safety_event"; message: string; timestamp?: string }
  | {
      type: "pending_approval_created";
      approval_id: string;
      symbol: string;
      final_action: string;
      quantity?: number;
      entry_price?: number;
      timestamp?: string;
    }
  | { type: "ping" };
