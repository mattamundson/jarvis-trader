"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import EngineWidget from "@/components/EngineWidget";

interface CircuitBreakerData {
  daily_pnl: number;
  daily_limit: number;
  daily_pnl_pct: number;
  daily_limit_pct: number;
  daily_limit_breached: boolean;
  drawdown_pct: number;
  drawdown_limit_pct: number;
  drawdown_breached: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  pnl_source: string;
  current_balance: number;
  starting_balance: number;
  orders_last_minute: number;
  all_clear: boolean;
}

function StatusDot({ active, danger }: { active: boolean; danger?: boolean }) {
  const dotColorClass = active ? (danger !== false ? "bg-[#ff4444]" : "bg-[#00ff88]") : "bg-[#00ff88]";

  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      <span
        className={`absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping ${dotColorClass}`}
      />
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dotColorClass}`} />
    </span>
  );
}

function BreachedDot({ breached }: { breached: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${breached ? "bg-[#ff4444]" : "bg-[#00ff88]"}`}
    />
  );
}

export function CircuitBreakerWidget() {
  return (
    <EngineWidget<CircuitBreakerData>
      endpoint="/safety/circuit-breakers"
      title="Circuit Breakers"
      refreshInterval={15_000}
      render={(data) => {
        const anyTripped = data.daily_limit_breached || data.drawdown_breached || data.kill_switch_active;

        const dailyLossProgress =
          data.daily_limit !== 0
            ? Math.min(1, Math.max(0, Math.abs(Math.min(0, data.daily_pnl)) / Math.abs(data.daily_limit)))
            : 0;

        const dailyPnlSign = data.daily_pnl >= 0 ? "+" : "";
        const displayDailyPnl = `${dailyPnlSign}$${data.daily_pnl.toFixed(0)}`;
        const displayDailyLimit = `-$${Math.abs(data.daily_limit).toFixed(0)} limit`;

        const displayDrawdown = `${(data.drawdown_pct * 100).toFixed(2)}%`;
        const displayDrawdownLimit = `${(Math.abs(data.drawdown_limit_pct) * 100).toFixed(1)}% limit`;

        const progressBarColorClass =
          dailyLossProgress >= 1
            ? "bg-[#ff4444]"
            : dailyLossProgress > 0.5
            ? "bg-[#ffcc00]"
            : "bg-[#00ff88]";

        const dailyPnlColorClass = data.daily_limit_breached
          ? "text-[#ff4444]"
          : data.daily_pnl < 0
          ? "text-[#ffcc00]"
          : "text-[#00ff88]";

        const drawdownColorClass = data.drawdown_breached
          ? "text-[#ff4444]"
          : data.drawdown_pct > Math.abs(data.drawdown_limit_pct) * 0.5
          ? "text-[#ffcc00]"
          : "text-[#00ff88]";

        const killSwitchColorClass = data.kill_switch_active ? "text-[#ff4444]" : "text-[#00ff88]";

        return (
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle>Circuit Breakers</CardTitle>
                <div className="flex items-center gap-2">
                  <Badge variant={anyTripped ? "bear" : "bull"}>
                    {anyTripped ? "TRADING HALTED" : "ALL CLEAR"}
                  </Badge>
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              {/* Row 1: Daily Loss Limit */}
              <div className="flex items-center gap-3">
                <BreachedDot breached={data.daily_limit_breached} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      Daily Loss Limit
                    </span>
                    <span
                      className={`font-mono text-xs font-bold tabular-nums ${dailyPnlColorClass}`}
                    >
                      {displayDailyPnl}{" "}
                      <span className="text-muted-foreground/60 font-normal">
                        / {displayDailyLimit}
                      </span>
                    </span>
                  </div>
                  {/* Progress bar */}
                  <div className="h-1.5 w-full rounded-full overflow-hidden bg-panel-border">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${progressBarColorClass}`}
                      style={{ width: `${dailyLossProgress * 100}%` }}
                    />
                  </div>
                </div>
                {data.daily_limit_breached && (
                  <Badge variant="bear">TRIPPED</Badge>
                )}
              </div>

              {/* Row 2: Max Drawdown */}
              <div className="flex items-center gap-3">
                <BreachedDot breached={data.drawdown_breached} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      Max Drawdown
                    </span>
                    <span
                      className={`font-mono text-xs font-bold tabular-nums ${drawdownColorClass}`}
                    >
                      {displayDrawdown}{" "}
                      <span className="text-muted-foreground/60 font-normal">
                        / {displayDrawdownLimit}
                      </span>
                    </span>
                  </div>
                </div>
                {data.drawdown_breached && (
                  <Badge variant="bear">TRIPPED</Badge>
                )}
              </div>

              {/* Row 3: Kill Switch */}
              <div className="flex items-center gap-3">
                <StatusDot active={data.kill_switch_active} danger />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      Kill Switch
                    </span>
                    <span
                      className={`font-mono text-xs font-bold uppercase tracking-wider ${killSwitchColorClass}`}
                    >
                      {data.kill_switch_active ? "ACTIVE" : "INACTIVE"}
                      {data.kill_switch_active && data.kill_switch_reason && (
                        <span className="ml-1 font-normal text-muted-foreground/60 normal-case tracking-normal">
                          ({data.kill_switch_reason})
                        </span>
                      )}
                    </span>
                  </div>
                </div>
                {data.kill_switch_active ? (
                  <Badge variant="bear">ACTIVE</Badge>
                ) : (
                  <Badge variant="neutral">INACTIVE</Badge>
                )}
              </div>

              {/* TRADING HALTED warning section */}
              {anyTripped && (
                <div
                  className="rounded-lg p-3 font-mono text-sm font-bold text-center bg-[#ff444415] border-2 border-[#ff444440] text-[#ff4444]"
                  role="alert"
                  aria-live="assertive"
                >
                  Trading Halted
                  <div className="mt-1 font-normal text-[10px] uppercase tracking-wider text-muted-foreground">
                    {[
                      data.daily_limit_breached && "Daily loss limit exceeded",
                      data.drawdown_breached && "Max drawdown exceeded",
                      data.kill_switch_active && "Kill switch active",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
              )}

              {/* Footer: source + refresh note */}
              <div className="flex items-center justify-between pt-1">
                {data.pnl_source && (
                  <span className="font-mono text-[9px] text-muted-foreground/50">
                    source: {data.pnl_source}
                  </span>
                )}
                <span className="font-mono text-[9px] text-muted-foreground/50 ml-auto">
                  auto-refresh 15s
                </span>
              </div>
            </CardContent>
          </Card>
        );
      }}
    />
  );
}
