"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchEngine } from "@/lib/api";

interface EngineWidgetProps<T> {
  endpoint: string;
  title: string;
  refreshInterval?: number;
  render: (data: T) => React.ReactNode;
  fallback?: React.ReactNode;
}

export default function EngineWidget<T>({
  endpoint,
  title,
  refreshInterval,
  render,
  fallback,
}: EngineWidgetProps<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const result = await fetchEngine<T>(endpoint);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, [endpoint]);

  useEffect(() => {
    fetchData();
    if (!refreshInterval) return;

    const id = setInterval(fetchData, refreshInterval);
    return () => clearInterval(id);
  }, [fetchData, refreshInterval]);

  const handleRetry = () => {
    setLoading(true);
    fetchData();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="font-mono text-xs animate-pulse text-muted-foreground/60">
          Loading {title}…
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg p-3 text-center space-y-2">
        <div
          className="rounded-lg p-3 text-center"
          style={{
            backgroundColor: "#ff444410",
            border: "1px solid #ff444430",
          }}
        >
          <span className="font-mono text-xs" style={{ color: "#ff4444" }}>
            {error}
          </span>
        </div>
        <button
          onClick={handleRetry}
          className="px-3 py-1.5 text-xs font-mono rounded bg-muted hover:bg-muted/80 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return fallback || null;
  }

  return <>{render(data)}</>;
}
