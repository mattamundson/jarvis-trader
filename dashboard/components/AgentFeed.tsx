import { useMemo } from "react";
import { Brain, Clock } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { signalToLabel, signalToColor, formatPercent } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import type { AgentDecision } from "@/lib/api";

const AGENT_ICONS: Record<string, string> = {
  technical_analyst: "📊",
  news_analyst: "📰",
  social_analyst: "💬",
  fundamental_analyst: "📋",
  bull_researcher: "🐂",
  bear_researcher: "🐻",
  trader: "⚡",
  risk_manager: "🛡",
  fund_manager: "🎯",
  regime_detector: "🌊",
};

function signalToVariant(signal: number): "bull" | "bear" | "warn" | "neutral" {
  if (signal >= 0.2) return "bull";
  if (signal <= -0.2) return "bear";
  if (Math.abs(signal) > 0.05) return "warn";
  return "neutral";
}

interface AgentFeedProps {
  decisions: AgentDecision[];
}

export function AgentFeed({ decisions }: AgentFeedProps) {
  const renderedDecisions = useMemo(
    () => decisions.map((d) => <AgentDecisionCard key={d.id} decision={d} />),
    [decisions]
  );

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-accent" />
          <CardTitle>Agent Activity</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        {decisions.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-8">
            No agent decisions yet — start the engine to begin analysis
          </p>
        ) : (
          <div className="space-y-3">
            {renderedDecisions}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AgentDecisionCard({ decision: d }: { decision: AgentDecision }) {
  const name = d.agent_name ?? d.source ?? "system";
  const icon = AGENT_ICONS[name] ?? "🤖";
  const agentLabel = name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const rawSignal = d.signal ?? (d.action === "buy" ? 0.5 : d.action === "sell" ? -0.5 : 0);
  const variant = signalToVariant(rawSignal);
  const signalLabel = signalToLabel(rawSignal);

  return (
    <div
      className="rounded-lg border border-border/50 bg-muted/20 p-3"
      role="article"
      aria-label={`${agentLabel} signal: ${signalLabel} with ${formatPercent((d.confidence ?? 0) * 100, 0)} confidence`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-base">{icon}</span>
          <span className="text-xs font-semibold text-foreground">{agentLabel}</span>
          {d.symbol && (
            <span className="font-mono text-xs text-muted-foreground">{d.symbol}</span>
          )}
        </div>
        <Badge variant={variant}>{signalToLabel(rawSignal)}</Badge>
      </div>

      {/* Signal bar */}
      <div className="mb-2 h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            rawSignal >= 0 ? "bg-bull ml-1/2" : "bg-bear"
          }`}
          style={{
            width: `${Math.abs(rawSignal) * 50}%`,
            marginLeft: rawSignal >= 0 ? "50%" : `${50 - Math.abs(rawSignal) * 50}%`,
          }}
        />
      </div>

      {(d.reasoning || d.summary) && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-1.5">
          {d.reasoning || d.summary}
        </p>
      )}

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDistanceToNow(new Date(d.created_at ?? d.timestamp ?? Date.now()), { addSuffix: true })}
        </span>
        <span>conf: {formatPercent((d.confidence ?? 0) * 100, 0)}</span>
        {d.latency_ms != null && <span>{d.latency_ms}ms</span>}
        {d.model_used && <span className="ml-auto text-xs opacity-60">{d.model_used}</span>}
      </div>
    </div>
  );
}
