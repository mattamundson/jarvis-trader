"use client";

/**
 * PAGE TABS
 * Reusable tab navigation for multi-section pages (Backtest, Strategies, Paper Trading).
 * Active tab persists in URL hash for deep linking.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export interface TabConfig {
  id: string;
  label: string;
  badge?: "beta" | "soon" | "new";
}

interface PageTabsProps {
  tabs: TabConfig[];
  activeTab: string;
  onTabChange: (id: string) => void;
  className?: string;
}

export function PageTabs({ tabs, activeTab, onTabChange, className = "" }: PageTabsProps) {
  return (
    <div
      className={`flex items-center gap-1 border-b ${className}`}
      style={{ borderColor: "#1a1a2e" }}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className="relative px-4 py-2.5 text-xs font-mono font-bold tracking-wider uppercase transition-colors flex items-center gap-1.5"
            style={{
              color: isActive ? "#00ff88" : "#555",
              borderBottom: isActive ? "2px solid #00ff88" : "2px solid transparent",
              marginBottom: "-1px",
            }}
          >
            {tab.label}
            {tab.badge === "soon" && (
              <span
                className="text-[8px] px-1 py-0.5 rounded"
                style={{ backgroundColor: "#1a1a2e", color: "#555" }}
              >
                SOON
              </span>
            )}
            {tab.badge === "beta" && (
              <span
                className="text-[8px] px-1 py-0.5 rounded"
                style={{ backgroundColor: "#00ccff15", color: "#00ccff" }}
              >
                BETA
              </span>
            )}
            {tab.badge === "new" && (
              <span
                className="text-[8px] px-1 py-0.5 rounded"
                style={{ backgroundColor: "#00ff8815", color: "#00ff88" }}
              >
                NEW
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Hook to manage tab state with URL hash persistence.
 * Usage: const [tab, setTab] = useTabState("overview", tabs);
 */
export function useTabState(defaultTab: string, tabs: TabConfig[]) {
  const [activeTab, setActiveTab] = useState(defaultTab);

  useEffect(() => {
    // Read hash on mount
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "");
      const found = tabs.find(t => t.id === hash);
      if (found) setActiveTab(found.id);
    }
  }, []);

  const handleTabChange = (id: string) => {
    setActiveTab(id);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#${id}`);
    }
  };

  return [activeTab, handleTabChange] as const;
}
