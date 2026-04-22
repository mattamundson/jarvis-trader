"use client";
import { useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { postEngine } from "@/lib/api";

interface TestResult {
  sent: boolean;
  message?: string;
  error?: string;
  timestamp: string;
}

export function NotificationTestPanel() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  const runTest = async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await postEngine<TestResult>("/notifications/whatsapp/test");
      setResult(data);
    } catch (err) {
      setResult({
        sent: false,
        error: String(err),
        timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Notification Test</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Send a test WhatsApp message to verify the notification channel is operational.
        </p>
        <button
          onClick={runTest}
          disabled={loading}
          className="rounded-md bg-accent/10 border border-accent/30 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Sending\u2026" : "Send Test Notification"}
        </button>
        {result && (
          <div className="rounded-lg border border-border p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Result:</span>
              <Badge variant={result.sent ? "bull" : "bear"}>
                {result.sent ? "SENT" : "FAILED"}
              </Badge>
            </div>
            {result.message && (
              <p className="text-xs text-muted-foreground break-all">{result.message}</p>
            )}
            {result.error && (
              <p className="text-xs text-red-400 break-all">{result.error}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {new Date(result.timestamp).toLocaleTimeString()}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
