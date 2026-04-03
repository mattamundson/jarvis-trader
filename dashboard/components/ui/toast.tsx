"use client";

import type { LucideIcon } from "lucide-react";
import { X, CheckCircle, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastVariant = "success" | "error" | "warning" | "info";

export interface ToastMessage {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

const variantStyles: Record<ToastVariant, string> = {
  success: "bg-bull/20 border-bull/40 text-bull",
  error: "bg-bear/20 border-bear/40 text-bear",
  warning: "bg-warn/20 border-warn/40 text-warn",
  info: "bg-accent/20 border-accent/40 text-accent",
};

const iconMap: Record<ToastVariant, LucideIcon> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertCircle,
  info: Info,
};

export function Toast({ toast, onDismiss }: ToastProps) {
  const Icon = iconMap[toast.variant];

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border px-4 py-3 text-sm font-medium transition-all animate-in slide-in-from-top-2 fade-in",
        variantStyles[toast.variant]
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="ml-2 inline-flex shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}