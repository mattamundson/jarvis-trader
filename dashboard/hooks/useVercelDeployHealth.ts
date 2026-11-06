import useSWR from "swr";

type DeployStatus = "READY" | "ERROR" | "BUILDING" | "UNKNOWN";

interface VercelDeployHealth {
  status: DeployStatus;
  url?: string;
  createdAt?: string;
}

async function fetcher(url: string): Promise<VercelDeployHealth> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("Failed to fetch Vercel deploy health");
  }
  return response.json();
}

export function useVercelDeployHealth() {
  return useSWR<VercelDeployHealth>("/api/vercel-deploy-health", fetcher, {
    refreshInterval: 30_000,
    shouldRetryOnError: false,
  });
}
