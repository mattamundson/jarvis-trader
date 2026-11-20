import { NextResponse } from "next/server";

type DeployStatus = "READY" | "ERROR" | "BUILDING" | "UNKNOWN";

interface VercelDeployment {
  uid: string;
  name: string;
  url: string;
  created: number;
  state: string;
  readyState: string;
  target: string;
}

interface VercelDeploymentsResponse {
  deployments: VercelDeployment[];
}

interface HealthResponse {
  status: DeployStatus;
  url?: string;
  createdAt?: string;
}

export const dynamic = "force-dynamic";

export async function GET() {
  const token = process.env.VERCEL_TOKEN;
  const projectId = "prj_U1ZIRR4wPJo0BMfBrSqfgpbpbXIS";
  const teamId = "team_LU4JL0l8BMbFKIAzLzI0S4yl";

  if (!token) {
    return NextResponse.json<HealthResponse>(
      { status: "UNKNOWN" },
      { status: 200 }
    );
  }

  try {
    const url = new URL("https://api.vercel.com/v6/deployments");
    url.searchParams.set("projectId", projectId);
    url.searchParams.set("teamId", teamId);
    url.searchParams.set("limit", "1");
    url.searchParams.set("target", "production");

    const response = await fetch(url.toString(), {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      return NextResponse.json<HealthResponse>(
        { status: "UNKNOWN" },
        { status: 200 }
      );
    }

    const data = (await response.json()) as VercelDeploymentsResponse;

    if (!data.deployments || data.deployments.length === 0) {
      return NextResponse.json<HealthResponse>(
        { status: "UNKNOWN" },
        { status: 200 }
      );
    }

    const latestDeploy = data.deployments[0];
    let status: DeployStatus = "UNKNOWN";

    if (latestDeploy.readyState === "READY") {
      status = "READY";
    } else if (latestDeploy.readyState === "ERROR") {
      status = "ERROR";
    } else if (
      latestDeploy.readyState === "BUILDING" ||
      latestDeploy.readyState === "QUEUED" ||
      latestDeploy.readyState === "INITIALIZING"
    ) {
      status = "BUILDING";
    }

    return NextResponse.json<HealthResponse>({
      status,
      url: latestDeploy.url,
      createdAt: new Date(latestDeploy.created).toISOString(),
    });
  } catch (error) {
    return NextResponse.json<HealthResponse>(
      { status: "UNKNOWN" },
      { status: 200 }
    );
  }
}
