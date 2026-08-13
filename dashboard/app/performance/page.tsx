import { Suspense } from "react";
import PerformanceWorkspace from "@/components/performance/PerformanceWorkspace";

// Route file for the summary-first /performance workspace (PRB
// dashboard-hardening Task 3). All page content lives in
// components/performance/PerformanceWorkspace.tsx + components/performance/sections/*
// -- this file only owns the route and the Suspense boundary that
// PerformanceWorkspace's useSearchParams() (?section=<id>) requires.
export default function PerformancePage() {
  return (
    <Suspense
      fallback={
        <div
          className="min-h-screen flex items-center justify-center text-sm"
          style={{ backgroundColor: "#050505", color: "#555" }}
        >
          Loading performance workspace…
        </div>
      }
    >
      <PerformanceWorkspace />
    </Suspense>
  );
}
