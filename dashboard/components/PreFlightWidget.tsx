"use client";
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle, AlertTriangle, RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";

type CheckResult = {
  name: string;
  status: "pass" | "fail" | "warn";
  detail: string;
};

type PreflightData = {
  all_pass: boolean;
  check_count: number;
  pass_count: number;
  fail_count: number;
  warn_count: number;
  checks: CheckResult[];
  timestamp: string;
};

const STATUS_ICON = {
  pass: <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />,
  fail: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  warn: <AlertTriangle className="h-3.5 w-3.5 text-yellow-500" />,
};

const STATUS_VARIANT: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  pass: "bull",
  fail: "bear",
  warn: "warn",
};

export function PreFlightWidget() {
  const [data, setData] = useState<PreflightData | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastRun, setLastRun] = useState<string | null>(null);

  const runCheck = () => {
    setLoading(true);
    fetchEngine<PreflightData>("/system/preflight")
      .then((d) => {
        setData(d);
        setLastRun(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    runCheck();
    const id = setInterval(runCheck, 120_000);
    return () => clearInterval(id);
  }, []);

  const overall = data?.all_pass
    ? "bull"
    : data && data.fail_count > 0
    ? "bear"
    : "warn";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Pre-Flight Check</CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <Badge variant={overall as "bull" | "bear" | "warn"}>
                {data.all_pass ? "READY" : `${data.fail_count} FAIL`}
              </Badge>
            )}
            <button
              onClick={runCheck}
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Re-run checks"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastRun && (
          <p className="text-xs text-muted-foreground">Last run: {lastRun}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {!data ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-8 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {data.checks.map((c) => (
              <div key={c.name} className="flex items-start gap-2.5 px-4 py-2">
                <span className="mt-0.5 shrink-0">{STATUS_ICON[c.status]}</span>
                <div className="min-w-0">
                  <span className="text-xs font-medium">{c.name}</span>
                  <p className="text-xs text-muted-foreground truncate">{c.detail}</p>
                </div>
                <Badge variant={STATUS_VARIANT[c.status] ?? "neutral"} className="ml-auto shrink-0 text-xs">
                  {c.status.toUpperCase()}
                </Badge>
              </div>
            ))}
          </div>
        )}
        {data && (
          <div className="px-4 py-2 border-t border-border bg-muted/30 flex gap-3 text-xs text-muted-foreground">
            <span className="text-green-500">{data.pass_count} pass</span>
            <span className="text-red-500">{data.fail_count} fail</span>
            <span className="text-yellow-500">{data.warn_count} warn</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
