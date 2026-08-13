import { Suspense } from "react";
import ValidationWorkspace from "@/components/validation/ValidationWorkspace";

// Route file for the summary-first /validation workspace (PRB
// dashboard-hardening Task 3). All page content lives in
// components/validation/ValidationWorkspace.tsx + components/validation/sections/*
// -- this file only owns the route and the Suspense boundary that
// ValidationWorkspace's useSearchParams() (?section=<id>) requires.
export default function ValidationPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex items-center justify-center text-sm text-muted-foreground">
          Loading validation workspace…
        </div>
      }
    >
      <ValidationWorkspace />
    </Suspense>
  );
}
