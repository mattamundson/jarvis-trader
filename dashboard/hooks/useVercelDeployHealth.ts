import useSWR from "swr";
import { localFetch } from "@/lib/api";

type DeployStatus = "READY" | "ERROR" | "BUILDING" | "UNKNOWN";

interface VercelDeployHealth {
  status: DeployStatus;
  url?: string;
  createdAt?: string;
}

export function useVercelDeployHealth() {
  return useSWR<VercelDeployHealth>("/api/vercel-deploy-health", localFetch, {
    refreshInterval: 30_000,
    shouldRetryOnError: false,
  });
}
