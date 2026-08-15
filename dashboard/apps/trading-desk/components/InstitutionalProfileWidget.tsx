"use client";

import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { RefreshCw, LayoutGrid, Target, Activity, Triangle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface InstitutionalProfile {
  symbol: string;
  current_price: number;
  volume_profile: {
    poc: number;
    vah: number;
    val: number;
  };
  harmonics: Array<{
    name: string;
    type: string;
    confidence: number;
    points: number;
  }>;
  regime: {
    value: string;
    description: string;
    adx: number;
    atr_ratio: number;
  };
  timeframe: string;
}

export function InstitutionalProfileWidget({ defaultSymbol = "MES" }: { defaultSymbol?: string }) {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [data, setData] = useState<InstitutionalProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchProfile = useCallback(async () => {
    setRefreshing(true);
    try {
      const json = await fetchEngine<InstitutionalProfile>(`/institutional/profile/${symbol}`);
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach engine");
    } finally {
      setRefreshing(false);
    }
  }, [symbol]);

  useEffect(() => {
    fetchProfile();
    const interval = setInterval(fetchProfile, 30_000);
    return () => clearInterval(interval);
  }, [fetchProfile]);

  const profile = data;
  const currentPrice = profile?.current_price ?? 0;
  const vProfile = profile?.volume_profile;
  const harmonics = profile?.harmonics ?? [];

  return (
    <Card className="border-2 border-indigo-500/20 bg-indigo-500/5 shadow-lg backdrop-blur-sm overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3 bg-indigo-500/10">
        <div className="flex items-center gap-2">
          <Target className="h-5 w-5 text-indigo-400" />
          <CardTitle className="text-sm font-bold uppercase tracking-widest text-indigo-100">
            Institutional Profile
          </CardTitle>
          <div className="flex bg-black/40 p-1 rounded-md ml-4 gap-1">
            {["MES", "MNQ", "MCL"].map(s => (
              <button 
                key={s}
                onClick={() => setSymbol(s)}
                className={cn(
                  "px-2 py-0.5 text-[10px] rounded transition-all font-bold",
                  symbol === s ? "bg-indigo-500 text-white" : "text-indigo-300/50 hover:text-indigo-200"
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <RefreshCw className={cn("h-3 w-3 text-indigo-400/50", refreshing && "animate-spin")} />
      </CardHeader>

      <CardContent className="pt-4 space-y-6">
        {/* Price & POC Relative Positioning */}
        {vProfile && (
          <div className="space-y-3">
            <div className="flex justify-between items-end mb-1">
              <span className="text-[10px] uppercase font-bold text-indigo-300/60">Volume Profile Levels</span>
              <span className="text-xs font-mono font-bold text-indigo-200">${currentPrice.toFixed(2)}</span>
            </div>
            
            <div className="relative h-24 w-full bg-black/60 rounded-lg border border-indigo-500/10 flex flex-col justify-between p-3 overflow-hidden">
                {/* Background Pattern */}
                <div className="absolute inset-0 opacity-10 pointer-events-none" 
                     style={{backgroundImage: 'radial-gradient(circle, #6366f1 1px, transparent 1px)', backgroundSize: '10px 10px'}} />
                
                {/* Levels */}
                <div className="relative z-10 flex flex-col h-full justify-between">
                    <div className="flex justify-between items-center group">
                        <span className="text-[10px] font-mono text-indigo-400/80 group-hover:text-indigo-300 transition-colors">VAH</span>
                        <div className="h-[1px] flex-grow mx-2 bg-indigo-500/20" />
                        <span className="text-[10px] font-mono font-bold text-indigo-300">${vProfile.vah.toFixed(2)}</span>
                    </div>

                    <div className="flex justify-between items-center group relative">
                        <span className="text-[10px] font-mono text-gold group-hover:text-amber-300 transition-colors">POC</span>
                        <div className="h-[1px] flex-grow mx-2 bg-amber-500/30" />
                        <span className="text-[10px] font-mono font-bold text-amber-300">${vProfile.poc.toFixed(2)}</span>
                    </div>

                    <div className="flex justify-between items-center group">
                        <span className="text-[10px] font-mono text-indigo-400/80 group-hover:text-indigo-300 transition-colors">VAL</span>
                        <div className="h-[1px] flex-grow mx-2 bg-indigo-500/20" />
                        <span className="text-[10px] font-mono font-bold text-indigo-300">${vProfile.val.toFixed(2)}</span>
                    </div>
                </div>

                {/* Price Indicator Overlay */}
                {currentPrice > 0 && (
                   <div 
                    className="absolute left-0 right-0 h-4 flex items-center pointer-events-none transition-all duration-700 ease-in-out"
                    style={{
                        top: `${((vProfile.vah - currentPrice) / (vProfile.vah - vProfile.val)) * 50 + 25}%`
                    }}
                   >
                     <div className="w-full h-[2px] bg-white/40 shadow-[0_0_10px_rgba(255,255,255,0.5)]" />
                     <div className="absolute right-3 px-1.5 py-0.5 bg-black/80 border border-white/20 rounded text-[9px] font-bold text-white tabular-nums">
                        NOW
                     </div>
                   </div>
                )}
            </div>
          </div>
        )}

        {/* Harmonics Section */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
                <Triangle className="h-4 w-4 text-purple-400" />
                <span className="text-[10px] uppercase font-bold text-purple-300/60">Harmonic Vision</span>
            </div>
            {profile?.regime && (
                <Badge className={cn(
                    "text-[9px] px-1.5 py-0 border-none uppercase font-black",
                    profile.regime.value === "trending" ? "bg-bull text-black" :
                    profile.regime.value === "ranging" ? "bg-indigo-500 text-white" :
                    profile.regime.value === "volatile" ? "bg-bear text-white" : "bg-muted text-white"
                )}>
                    {profile.regime.value}
                </Badge>
            )}
          </div>

          {profile?.regime && (
              <div className="p-2 rounded bg-indigo-500/10 border border-indigo-500/20 mb-2">
                  <div className="text-[10px] text-indigo-200 font-bold mb-1 uppercase tracking-tighter">
                      Deterministic Regime Status
                  </div>
                  <div className="text-[9px] text-indigo-300/70 leading-tight italic">
                      "{profile.regime.description}"
                  </div>
              </div>
          )}

          <div className="grid grid-cols-1 gap-2">
            {harmonics.length > 0 ? (
              harmonics.map((p, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded bg-purple-500/10 border border-purple-500/20 group hover:bg-purple-500/20 transition-all">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "w-1.5 h-1.5 rounded-full animate-pulse",
                      p.type === "bullish" ? "bg-green-400" : "bg-red-400"
                    )} />
                    <div>
                      <div className="text-xs font-bold text-purple-100">{p.name}</div>
                      <div className="text-[9px] text-purple-300/60 uppercase font-mono">{p.type} REVERSAL</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-mono font-bold text-purple-200">${p.points.toFixed(2)}</div>
                    <div className="text-[9px] text-purple-400 font-bold">{Math.round(p.confidence * 100)}% CONF</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center justify-center p-4 rounded bg-black/40 border border-indigo-500/5">
                <Activity className="h-5 w-5 text-indigo-500/20 mb-2" />
                <span className="text-[10px] text-indigo-300/40 font-mono tracking-tighter">SCANNING FOR XABCD STRUCTURES</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center pt-2 border-t border-indigo-500/10">
            <span className="text-[9px] font-mono text-indigo-300/40 uppercase">Phase 4 Institutional Data</span>
            <Badge variant="neutral" className="text-[9px] px-1 py-0 border-indigo-500/30 text-indigo-400">
                TF: {profile?.timeframe || "15m"}
            </Badge>
        </div>
      </CardContent>
    </Card>
  );
}
