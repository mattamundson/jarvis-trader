"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import { Toast } from "@/components/ui/toast";
import { soundAlertManager } from "@/lib/sound-alerts";
import type { ToastMessage, ToastVariant } from "@/components/ui/toast";

interface ToastContextType {
  addToast: (message: string, variant: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const addToast = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    const toast: ToastMessage = { id, message, variant };

    setToasts((prev) => [...prev, toast]);

    // Play appropriate sound based on variant
    switch (variant) {
      case "success":
        soundAlertManager.orderFill().catch(() => {
          /* ignore audio errors */
        });
        break;
      case "error":
        soundAlertManager.error().catch(() => {
          /* ignore audio errors */
        });
        break;
      case "warning":
        soundAlertManager.circuitBreakerWarning().catch(() => {
          /* ignore audio errors */
        });
        break;
      case "info":
      default:
        // No sound for info toasts
        break;
    }

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 max-w-sm space-y-2 pointer-events-none">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <Toast toast={toast} onDismiss={dismissToast} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextType {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}
