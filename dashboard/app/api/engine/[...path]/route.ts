import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function getEngineBaseUrl(): string {
  const url = process.env.ENGINE_URL ?? process.env.NEXT_PUBLIC_ENGINE_URL;
  if (!url) {
    throw new Error(
      "Engine URL not configured. Set ENGINE_URL or NEXT_PUBLIC_ENGINE_URL environment variable."
    );
  }
  return url;
}

function getEngineApiKey(): string | undefined {
  return process.env.ENGINE_API_KEY ?? process.env.NEXT_PUBLIC_ENGINE_API_KEY;
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${getEngineBaseUrl()}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const engineApiKey = getEngineApiKey();
  if (engineApiKey) {
    headers.set("X-API-Key", engineApiKey);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function OPTIONS(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}
