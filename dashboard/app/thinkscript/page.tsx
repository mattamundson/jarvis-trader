"use client";

import { FileCode } from "lucide-react";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";
import { ThinkscriptRegistry } from "@/components/ThinkscriptRegistry";
import { GenerateStudyPanel } from "./GenerateStudyPanel";

export default function ThinkScriptPage() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      {/*
        Unconditional — not gated on generation state. The engine's
        /thinkscript/generate handler (engine/routers/thinkscript_router.py)
        swallows technical-analyst failures (`except Exception: pass`), so a
        generated script can carry zero real TA behind it with no field in the
        response to reveal that. The registry side is a read-only catalog and
        not itself unvalidated, but it sits on the same route as generation, so
        the banner stays mounted for the whole page rather than only the
        generate panel — see lib/api.ts's ThinkScriptGenerateResponse doc
        comment and docs/backlog/DASHBOARD_PUNCHLIST.md "Engine follow-ups".
      */}
      <ExploratoryBanner what="ThinkScript generation runs LLM-backed code synthesis with an unverifiable technical-analysis grounding" />

      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight text-foreground">
          <FileCode className="h-5 w-5 text-accent" />
          ThinkScript
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Registry of ThinkScript studies wired into JARVIS, their documentation, and an
          on-demand generator for new studies. Analysis-only — nothing here writes to
          ThinkorSwim automatically.
        </p>
      </div>

      <ThinkscriptRegistry />

      <GenerateStudyPanel />
    </div>
  );
}
