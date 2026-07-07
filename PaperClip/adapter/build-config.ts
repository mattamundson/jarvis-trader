/**
 * Jarvis-Trader Pipeline Adapter — ui/build-config.ts
 * Defines the config form shown in Paperclip UI when creating an agent.
 */

import type { AdapterConfigSchema } from "@paperclipai/sdk";

export const configSchema: AdapterConfigSchema = {
  fields: [
    {
      key: "engine_url",
      label: "Engine URL",
      type: "string",
      default: "http://localhost:8010",
      description: "FastAPI trading engine base URL",
    },
    {
      key: "symbol",
      label: "Trading Symbol",
      type: "string",
      default: "AAPL",
      description: "Ticker symbol to analyze (e.g. AAPL, TSLA, SPY)",
    },
    {
      key: "timeframe",
      label: "Timeframe",
      type: "select",
      options: ["1m", "5m", "15m", "1h", "4h", "1d"],
      default: "1d",
    },
    {
      key: "max_tokens",
      label: "Max tokens per agent",
      type: "number",
      default: 4000,
      description: "Hard token budget per pipeline agent. Prevents Anthropic 400 errors.",
    },
    {
      key: "tier3_confirm",
      label: "Require Tier 3 approval for live trades",
      type: "boolean",
      default: true,
      description: "Maps to Paperclip governance approval gate",
    },
  ],
};
