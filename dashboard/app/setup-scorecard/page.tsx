import { notFound } from "next/navigation";
import { isOpsEnabled } from "@/lib/opsAuth";
import SetupScorecardClient from "./SetupScorecardClient";

export default function SetupScorecardPage() {
  if (!isOpsEnabled()) {
    notFound();
  }

  return <SetupScorecardClient />;
}
