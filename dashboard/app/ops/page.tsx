import { notFound } from "next/navigation";
import { isOpsEnabled } from "@/lib/opsAuth";
import OpsPageClient from "./OpsPageClient";

export default function OpsPage() {
  if (!isOpsEnabled()) {
    notFound();
  }

  return <OpsPageClient />;
}
