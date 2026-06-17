"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ExternalLink, Archive } from "lucide-react";
import Link from "next/link";

export default function DashboardRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    // Auto-redirect after 2s
    const t = setTimeout(() => router.replace("/command-center"), 2000);
    return () => clearTimeout(t);
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 px-6">
      <div className="flex items-center gap-3 text-muted-foreground">
        <Archive className="h-6 w-6" />
        <span className="font-mono text-sm uppercase tracking-widest">Legacy View Retired</span>
      </div>
      <h1 className="text-2xl font-bold text-foreground text-center">
        Dashboard has moved to Command Center
      </h1>
      <p className="text-muted-foreground text-center max-w-md text-sm">
        The legacy EOD view has been retired. All functionality is now available in Command Center.
        Redirecting automatically…
      </p>
      <Link
        href="/command-center"
        className="flex items-center gap-2 rounded-lg bg-accent/20 px-5 py-2.5 text-sm font-semibold text-accent hover:bg-accent/30 transition-colors"
      >
        <ExternalLink className="h-4 w-4" />
        Go to Command Center
      </Link>
    </div>
  );
}
