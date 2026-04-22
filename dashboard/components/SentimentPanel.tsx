import { MessageSquare, Newspaper, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatPercent } from "@/lib/utils";
import type { SentimentData } from "@/lib/api";

const SOURCE_CONFIG = {
  reddit: { icon: MessageSquare, label: "Reddit", color: "text-warn" },
  news: { icon: Newspaper, label: "News", color: "text-info" },
  stocktwits: { icon: TrendingUp, label: "StockTwits", color: "text-bull" },
};

interface SentimentPanelProps {
  sentiments: SentimentData[];
}

export function SentimentPanel({ sentiments }: SentimentPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sentiment</CardTitle>
      </CardHeader>
      <CardContent>
        {sentiments.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-4">
            No sentiment data
          </p>
        ) : (
          <div className="space-y-3">
            {sentiments.map((s, i) => (
              <SentimentRow key={i} sentiment={s} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SentimentRow({ sentiment: s }: { sentiment: SentimentData }) {
  const config = SOURCE_CONFIG[s.source as keyof typeof SOURCE_CONFIG] ?? {
    icon: MessageSquare,
    label: s.source,
    color: "text-muted-foreground",
  };
  const Icon = config.icon;

  const scoreColor =
    s.score >= 0.1
      ? "text-bull"
      : s.score <= -0.1
      ? "text-bear"
      : "text-warn";

  const barWidth = Math.abs(s.score) * 100;
  const barColor = s.score >= 0 ? "bg-bull" : "bg-bear";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5">
          <Icon className={`h-3.5 w-3.5 ${config.color}`} />
          <span className="text-muted-foreground">{config.label}</span>
          {s.symbol && (
            <span className="font-mono text-muted-foreground/60">{s.symbol}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground/60">{s.post_count} posts</span>
          <span className={`tabular-nums font-medium ${scoreColor}`}>
            {s.score >= 0 ? "+" : ""}
            {s.score.toFixed(2)}
          </span>
        </div>
      </div>
      {/* Sentiment bar — centered at 0 */}
      <div className="relative h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`absolute top-0 h-full rounded-full ${barColor}`}
          style={{
            width: `${barWidth / 2}%`,
            left: s.score >= 0 ? "50%" : `${50 - barWidth / 2}%`,
          }}
        />
        {/* Center line (divider) */}
        <div
          className="absolute left-1/2 top-0 h-full w-px bg-border"
          aria-label="Sentiment neutral point"
          role="separator"
        />
      </div>
      {/* Text label for color indicator */}
      <div className="flex items-center justify-between text-xs mt-1">
        <span className="text-muted-foreground">
          {s.score > 0 ? "Bullish" : s.score < 0 ? "Bearish" : "Neutral"}
        </span>
      </div>
    </div>
  );
}
