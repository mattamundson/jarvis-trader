"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postEngine } from "@/lib/api";

interface KillSwitchProps {
  isActive: boolean;
  reason?: string;
  onToggle: () => void;
}

export function KillSwitch({ isActive, reason, onToggle }: KillSwitchProps) {
  const [confirmingHalt, setConfirmingHalt] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [confirmingResume, setConfirmingResume] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleActivate() {
    if (!confirmingHalt) {
      setError(null);
      setConfirmingHalt(true);
      return;
    }
    if (confirmText !== "CONFIRM KILL") return;

    setIsSubmitting(true);
    setError(null);
    try {
      await postEngine("/safety/kill-switch/activate", { reason: "manual_dashboard" });
      onToggle();
    } catch {
      setError("Failed to activate kill switch");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDeactivate() {
    if (!confirmingResume) {
      setError(null);
      setConfirmingResume(true);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await postEngine("/safety/kill-switch/deactivate");
      onToggle();
    } catch {
      setError("Failed to deactivate kill switch");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{isActive ? "KILL SWITCH ACTIVE" : "Trading Active"}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isActive ? (
          <>
            {reason ? <p className="text-sm text-muted-foreground">Reason: {reason}</p> : null}
            <Button
              type="button"
              variant="destructive"
              onClick={handleDeactivate}
              disabled={isSubmitting}
              aria-label="Deactivate kill switch and resume trading"
            >
              {confirmingResume ? "Confirm Resume Trading" : "Deactivate Kill Switch and Resume Trading"}
            </Button>
          </>
        ) : (
          <>
            <Button
              type="button"
              variant="destructive"
              onClick={handleActivate}
              disabled={isSubmitting}
            >
              Emergency Stop
            </Button>
            {confirmingHalt ? (
              <div className="space-y-2">
                <input
                  className="h-9 w-full rounded border border-border bg-background px-3 text-sm"
                  placeholder="Type here..."
                  value={confirmText}
                  onChange={(event) => setConfirmText(event.target.value)}
                />
                <Button
                  type="button"
                  variant="destructive"
                  onClick={handleActivate}
                  disabled={isSubmitting || confirmText !== "CONFIRM KILL"}
                >
                  HALT SYSTEM
                </Button>
              </div>
            ) : null}
          </>
        )}
        {error ? <p className="text-sm text-bear">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
