import Link from "next/link";
import type { ReactNode } from "react";

export default function CommandCenterV2Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <nav className="border-b border-zinc-900 bg-black px-5 py-2 text-zinc-300">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 text-xs font-semibold uppercase tracking-[0.12em]">
          <span className="text-zinc-600">Command Center V2</span>
          <Link href="/command-center-v2" className="hover:text-white">Cockpit</Link>
          <Link href="/command-center-v2/trade" className="hover:text-white">Manual Paper Trade</Link>
          <span className="ml-auto rounded-full border border-amber-500/30 px-2 py-1 text-amber-300">Paper control plane</span>
        </div>
      </nav>
      {children}
    </>
  );
}
