"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface ScheduleItem {
  label: string;
  time: string;
  note?: string;
  badge: string | null;
  badgeVariant: BadgeVariant;
}

export function TradingScheduleCard({ className }: { className?: string }) {
  const scheduleItems: ScheduleItem[] = [
    { label: "Pre-Market", time: "5:00 PM – 8:30 AM CT", note: "Previous day 5 PM", badge: "ACTIVE", badgeVariant: "neutral" as const },
    { label: "RTH Open", time: "8:30 AM CT", note: "Primary trading window", badge: "RTH", badgeVariant: "bull" as const },
    { label: "Daily Settlement", time: "3:00 PM CT", note: "Mon–Fri", badge: null, badgeVariant: "neutral" as const },
    { label: "EOD Snapshot", time: "3:05 PM CT", note: "Auto-saved Mon–Fri", badge: "AUTO", badgeVariant: "info" as const },
    { label: "RTH Close", time: "3:15 PM CT", note: "End of primary window", badge: null, badgeVariant: "neutral" as const },
    { label: "After-Hours", time: "3:15 – 4:00 PM CT", note: "Limited liquidity", badge: null, badgeVariant: "neutral" as const },
    { label: "Weekly Close", time: "4:00 PM CT Friday", note: "Market reopens Sun 5 PM", badge: "WEEKEND", badgeVariant: "warn" as const },
  ];

  return (
    <Card className={cn(className)}>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Trading Schedule</CardTitle>
        <Badge variant="info">MES Futures</Badge>
      </CardHeader>
      <CardContent>
        {/* Schedule table */}
        <div className="space-y-2">
          {scheduleItems.map((item) => (
            <div
              key={item.label}
              className="flex justify-between items-center py-1.5 border-b border-border last:border-0"
            >
              <div>
                <p className="text-sm font-medium">{item.label}</p>
                {item.note && (
                  <p className="text-xs text-muted-foreground">{item.note}</p>
                )}
              </div>
              <div className="text-right">
                <p className="text-sm font-mono">{item.time}</p>
                {item.badge && (
                  <Badge variant={item.badgeVariant} className="text-xs">
                    {item.badge}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Automated actions */}
        <div className="mt-4 rounded bg-muted p-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Automated Actions
          </p>
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>• EOD snapshot saved daily at 3:05 PM CT</p>
            <p>• Circuit breakers checked on every trade entry</p>
            <p>• WhatsApp alerts sent on signal events</p>
            <p>• Morning briefing available via /notifications/morning-briefing</p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground mt-3">
          All times Central Time (CT) • MES trades 23h/day except daily settlement break
        </p>
      </CardContent>
    </Card>
  );
}
