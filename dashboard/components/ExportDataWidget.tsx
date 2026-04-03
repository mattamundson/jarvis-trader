"use client";
import { useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Download } from "lucide-react";
import { fetchEngineRaw } from "@/lib/api";

interface ExportItem {
  label: string;
  endpoint: string;
  filename: string;
  description: string;
}

const EXPORTS: ExportItem[] = [
  {
    label: "Paper Trades CSV",
    endpoint: "/portfolio/export/trades.csv",
    filename: "paper_trades.csv",
    description: "All paper trade records with entry/exit prices, P&L, and timestamps",
  },
  {
    label: "Daily P&L CSV",
    endpoint: "/portfolio/export/daily-pnl.csv",
    filename: "daily_pnl.csv",
    description: "Daily P&L summaries for the entire paper trading phase",
  },
];

export function ExportDataWidget() {
  const [downloading, setDownloading] = useState<string | null>(null);
  const [lastExport, setLastExport] = useState<Record<string, string>>({});

  const handleDownload = async (item: ExportItem) => {
    setDownloading(item.endpoint);
    try {
      const res = await fetchEngineRaw(item.endpoint);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = item.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setLastExport((prev) => ({
        ...prev,
        [item.endpoint]: new Date().toLocaleTimeString(),
      }));
    } catch (err) {
      console.error("Export failed:", err);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Export Data</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {EXPORTS.map((item) => (
          <div
            key={item.endpoint}
            className="flex items-center justify-between gap-4 rounded-lg border border-border p-3"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">{item.label}</p>
              <p className="text-xs text-muted-foreground truncate">{item.description}</p>
              {lastExport[item.endpoint] && (
                <p className="text-xs text-muted-foreground mt-1">
                  Last exported: {lastExport[item.endpoint]}
                </p>
              )}
            </div>
            <button
              onClick={() => handleDownload(item)}
              disabled={downloading === item.endpoint}
              className="flex items-center gap-1.5 rounded-md bg-accent/10 border border-accent/30 px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Download className="h-3 w-3" />
              {downloading === item.endpoint ? "Downloading\u2026" : "Download"}
            </button>
          </div>
        ))}
        <p className="text-xs text-muted-foreground pt-1">
          CSV files include all paper trades recorded since engine initialization.
        </p>
      </CardContent>
    </Card>
  );
}
