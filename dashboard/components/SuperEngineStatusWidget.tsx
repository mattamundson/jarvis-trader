"use client";

import React, { useEffect, useState } from "react";
import { fetchSuperEngineStatus, SuperEngineStatusResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Cpu, Globe, Shield, MessageSquare, Database, RefreshCw, Radar } from "lucide-react";

export const SuperEngineStatusWidget: React.FC = () => {
  const [status, setStatus] = useState<SuperEngineStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const loadStatus = async () => {
    try {
      const data = await fetchSuperEngineStatus();
      setStatus(data);
    } catch (err) {
      console.error("Failed to fetch super engine status", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 30000); // 30s poll
    return () => clearInterval(interval);
  }, []);

  const components = [
    { key: "polymarket", label: "Polymarket CLOB", icon: Globe, color: "text-blue-400" },
    { key: "openbb", label: "OpenBB Hub", icon: Database, color: "text-green-400" },
    { key: "regime_guard", label: "Regime Guard", icon: Shield, color: "text-purple-400" },
    { key: "sentiment_bridge", label: "Sentiment Bridge", icon: MessageSquare, color: "text-yellow-400" },
    { key: "model_drawer", label: "FreqAI Model Drawer", icon: Cpu, color: "text-pink-400" },
    { key: "arb_scout", label: "Arb Scout", icon: Radar, color: "text-red-400" },
  ];

  return (
    <Card className="bg-black/40 border-neutral-800 backdrop-blur-md shadow-2xl">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-neutral-400">
          Super-Engine Infrastructure
        </CardTitle>
        <RefreshCw className={`h-4 w-4 text-neutral-500 ${loading ? 'animate-spin' : ''}`} />
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        <div className="grid grid-cols-1 gap-3">
          {components.map((c) => {
            const compStatus = status?.[c.key as keyof SuperEngineStatusResponse];
            const isActive = compStatus?.active;

            return (
              <div 
                key={c.key} 
                className="flex items-center justify-between p-3 rounded-lg bg-neutral-900/50 border border-neutral-800/50 hover:bg-neutral-800/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-md bg-black/40 ${c.color}`}>
                    <c.icon className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-neutral-200">{c.label}</div>
                    <div className="text-[10px] text-neutral-500 font-mono">
                      {compStatus?.type || "v1.0.0"}
                    </div>
                  </div>
                </div>
                <Badge 
                  variant={isActive ? "bull" : "bear"}
                  className={isActive ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-red-500/20 text-red-400 border-red-500/30"}
                >
                  {isActive ? "ACTIVE" : "OFFLINE"}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
