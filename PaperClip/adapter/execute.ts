/**
 * Jarvis-Trader Pipeline Adapter — server/execute.ts
 * Paperclip calls this to run one pipeline cycle.
 * Wraps the FastAPI engine at localhost:8010.
 */

import type { AdapterExecuteInput, AdapterExecuteOutput } from "@paperclipai/sdk";

export async function execute(input: AdapterExecuteInput): Promise<AdapterExecuteOutput> {
  const { config, task, onHeartbeat } = input;

  const engineUrl = config.engine_url ?? "http://localhost:8010";
  const symbol = config.symbol ?? task?.metadata?.symbol ?? "AAPL";
  const timeframe = config.timeframe ?? "1d";
  const maxTokens = config.max_tokens ?? 4000;

  onHeartbeat({ status: "running", message: `Starting pipeline for ${symbol}` });

  try {
    const response = await fetch(`${engineUrl}/api/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol,
        timeframe,
        max_tokens_per_agent: maxTokens,
        task_id: task?.id,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      onHeartbeat({ status: "failed", message: `Engine error: ${error}` });
      return { success: false, error };
    }

    const result = await response.json();

    // Report token usage back to Paperclip for budget tracking
    const tokenUsage = result.token_usage ?? {};
    onHeartbeat({
      status: "completed",
      message: `Pipeline complete. Decision: ${result.decision ?? "N/A"}`,
      metadata: {
        token_usage: tokenUsage,
        total_tokens: Object.values(tokenUsage as Record<string, number>).reduce((a, b) => a + b, 0),
        decision: result.decision,
        confidence: result.confidence,
      },
    });

    return { success: true, output: result };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    onHeartbeat({ status: "failed", message: `Connection error: ${msg}` });
    return { success: false, error: msg };
  }
}
