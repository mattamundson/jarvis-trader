"use client";

/**
 * COMING SOON PAGE
 * Dark-themed placeholder for pages that are not yet production-ready.
 * Gates unfinished pages so they don't erode trust by showing empty 502 states.
 */

import React from "react";
import { Construction } from "lucide-react";

interface ComingSoonPageProps {
  title: string;
  description: string;
  eta?: string;
  features?: string[];
}

export function ComingSoonPage({ title, description, eta, features }: ComingSoonPageProps) {
  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ backgroundColor: "#050505" }}
    >
      <div className="max-w-lg w-full mx-auto px-8 text-center">
        {/* Status badge */}
        <div className="flex justify-center mb-6">
          <span
            className="inline-flex items-center gap-2 text-[10px] font-mono font-bold uppercase tracking-[0.2em] px-3 py-1.5 rounded-full"
            style={{
              backgroundColor: "#1a1a2e",
              color: "#555",
              border: "1px solid #2a2a45",
            }}
          >
            <Construction className="h-3 w-3" />
            In Development
          </span>
        </div>

        {/* Title */}
        <h1
          className="text-2xl font-mono font-bold tracking-tight mb-3"
          style={{ color: "#e0e0e0" }}
        >
          {title}
        </h1>

        {/* Description */}
        <p
          className="text-sm font-mono leading-relaxed mb-6"
          style={{ color: "#555" }}
        >
          {description}
        </p>

        {/* Feature list */}
        {features && features.length > 0 && (
          <div
            className="rounded-lg p-4 mb-6 text-left space-y-2"
            style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
          >
            <p
              className="text-[10px] font-mono font-bold uppercase tracking-[0.15em] mb-3"
              style={{ color: "#555" }}
            >
              Planned Features
            </p>
            {features.map((f, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-[10px] mt-0.5" style={{ color: "#2a2a45" }}>▸</span>
                <span className="text-xs font-mono" style={{ color: "#555" }}>{f}</span>
              </div>
            ))}
          </div>
        )}

        {/* ETA */}
        {eta && (
          <p
            className="text-[10px] font-mono"
            style={{ color: "#333" }}
          >
            Expected: {eta}
          </p>
        )}
      </div>
    </div>
  );
}
