"use client";

import { useState } from "react";
import { Play, Sparkles, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  generateThinkScript,
  normalizeJarvisSymbolInput,
  type ThinkScriptGenerateResponse,
} from "@/lib/api";

const TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"];

/**
 * POST /thinkscript/generate panel. Deliberately has NO "verified" or
 * "grounded" state to show — see the honesty note on ThinkScriptGenerateResponse
 * in lib/api.ts: the engine can return a fully-formed script with zero real
 * technical analysis behind it and there is currently no field that would tell
 * us. The per-result warning below plus the page-level ExploratoryBanner are the
 * only mitigations available client-side today.
 */
export function GenerateStudyPanel() {
  const [symbol, setSymbol] = useState("MES");
  const [timeframe, setTimeframe] = useState("15m");
  const [isFutures, setIsFutures] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ThinkScriptGenerateResponse | null>(null);

  async function handleGenerate() {
    const sym = normalizeJarvisSymbolInput(symbol);
    if (!sym) {
      setError("Enter a symbol first.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const res = await generateThinkScript({
        symbol: sym,
        timeframe,
        is_futures: isFutures,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
      setResult(null);
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5" />
          Generate a study
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-0">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Symbol</span>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="w-24 rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-xs uppercase text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Timeframe</span>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 pb-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={isFutures}
              onChange={(e) => setIsFutures(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border"
            />
            Futures
          </label>
          <Button size="sm" onClick={handleGenerate} disabled={pending} className="ml-auto">
            <Play className={`h-3.5 w-3.5 ${pending ? "animate-pulse" : ""}`} />
            {pending ? "Generating…" : "Generate"}
          </Button>
        </div>

        {error && (
          <p className="flex items-center gap-1.5 rounded-md border border-bear/30 bg-bear/5 px-3 py-2 text-xs text-bear">
            <TriangleAlert className="h-3.5 w-3.5 shrink-0" />
            {error}
          </p>
        )}

        {result && (
          <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
            <p className="flex items-start gap-1.5 rounded-md border border-warn/30 bg-warn/10 px-2.5 py-1.5 text-[11px] text-warn">
              <TriangleAlert className="h-3 w-3 mt-0.5 shrink-0" />
              This response cannot currently tell you whether real technical
              analysis backed this generation — the engine silently proceeds on
              analyst failure. Review the code before use.
            </p>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-mono text-sm font-semibold text-foreground">{result.title}</h3>
              <span className="font-mono text-[10px] text-muted-foreground/70">
                {result.symbol} · {result.timeframe} ·{" "}
                {new Date(result.timestamp).toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                })}
              </span>
            </div>

            {result.description && (
              <p className="text-xs text-muted-foreground">{result.description}</p>
            )}

            {result.signals_included?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.signals_included.map((sig) => (
                  <Badge key={sig} variant="info" className="font-mono">
                    {sig}
                  </Badge>
                ))}
              </div>
            )}

            <pre className="max-h-[360px] overflow-auto rounded-md border border-border bg-background p-3 font-mono text-[11px] leading-relaxed text-foreground/90">
              {result.code}
            </pre>

            {result.usage_instructions && (
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Usage
                </p>
                <p className="whitespace-pre-wrap text-xs text-muted-foreground">
                  {result.usage_instructions}
                </p>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
