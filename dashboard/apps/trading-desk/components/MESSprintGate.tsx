"use client";

import React, { useEffect, useState } from "react";
import { fetchEngine } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, XCircle, AlertCircle } from "lucide-react";

const POLL_MS = 60_000;

type GateCheck = {
  name: string;
  pass: boolean;
  value?: string;
  detail?: string;
};

type GateData = {
  overall: "PASS" | "PENDING" | "FAIL";
  ready_for_live: boolean;
  checks: GateCheck[];
  timestamp: string;
  notes?: string;
};

const overallVariant = (overall: GateData["overall"]): "bull" | "warn" | "bear" => {
  if (overall === "PASS") return "bull";
  if (overall === "PENDING") return "warn";
  return "bear";
};

export const MESSprintGate: React.FC = () => {
  const [data, setData] = useState<GateData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const resp = await fetchEngine<GateData>("/system/mes-sprint-gate");
        if (!cancelled) {
          setData(resp);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">MES Sprint Gate</CardTitle>
          {data && (
            <Badge variant={overallVariant(data.overall)} className="text-xs font-mono">
              {data.overall}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="text-xs text-red-500 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> {error}
          </div>
        )}
        {!error && !data && (
          <div className="text-xs text-muted-foreground">Loading…</div>
        )}
        {data && (
          <>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {data.checks.map((c) => (
                <div key={c.name} className="flex items-center gap-1.5 text-xs">
                  {c.pass ? (
                    <CheckCircle className="w-3 h-3 text-green-500 shrink-0" />
                  ) : (
                    <XCircle className="w-3 h-3 text-red-500 shrink-0" />
                  )}
                  <span className="font-mono truncate" title={c.detail ?? ""}>
                    {c.name}
                  </span>
                  {c.value && (
                    <span className="text-muted-foreground">({c.value})</span>
                  )}
                </div>
              ))}
            </div>
            <div className="text-[10px] text-muted-foreground mt-2">
              {new Date(data.timestamp).toLocaleTimeString()}
              {data.notes ? ` · ${data.notes}` : ""}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default MESSprintGate;
