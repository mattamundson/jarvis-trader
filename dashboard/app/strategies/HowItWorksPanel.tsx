"use client";

import { SectionHeader } from "./SectionHeader";

export function HowItWorksPanel() {
  const steps = [
    { icon: "1", label: "Fetch Data", desc: "IBKR → Polygon → yfinance fallback. 4yr train + 6mo OOS test." },
    { icon: "2", label: "Compute Indicators", desc: "signals.py compute_all_indicators() → 18-feature state space (STC, ATR, regime, volume)." },
    { icon: "3", label: "Train PPO", desc: "stable-baselines3 MlpPolicy. Reward = P&L/ATR − hold_cost − entry_cost." },
    { icon: "4", label: "Evaluate OOS", desc: "Run agent on test set. Check all 6 validation gates." },
    { icon: "5", label: "Save + Validate", desc: "Model saved to data/rl_models/. Must PASS all gates before paper trading." },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader title="How It Works" subtitle="PPO reinforcement learning pipeline" />
      <div className="flex flex-wrap gap-3">
        {steps.map(({ icon, label, desc }) => (
          <div
            key={icon}
            className="flex items-start gap-3 rounded-lg p-3 flex-1 min-w-[180px] bg-[#111] border border-panel-border"
          >
            <div
              className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full font-mono text-xs font-bold bg-[#00ff8820] text-[#00ff88]"
            >
              {icon}
            </div>
            <div>
              <div className="font-mono text-xs font-bold mb-0.5 text-[#e0e0e0]">{label}</div>
              <div className="font-mono text-[10px] text-[#555]">{desc}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 border-t border-panel-border">
        {[
          { label: "State Features", value: "18" },
          { label: "Action Space", value: "4  HOLD/BUY/SELL/CLOSE" },
          { label: "Algorithm", value: "PPO  MlpPolicy" },
          { label: "Safety", value: "SafetyLayer  every action" },
        ].map(({ label, value }) => (
          <div key={label}>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">{label}</div>
            <div className="font-mono text-xs font-bold text-[#00d4ff]">{value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
