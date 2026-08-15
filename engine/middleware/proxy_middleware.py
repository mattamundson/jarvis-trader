import httpx
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import StreamingResponse
from starlette.types import ASGIApp

class ProxyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, ops_url: str, research_url: str):
        super().__init__(app)
        self.ops_url = ops_url
        self.research_url = research_url
        self.client = httpx.AsyncClient()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path.startswith("/api/ops/"):
            target_url = f"{self.ops_url}{path.replace('/api/ops', '')}"
            return await self._proxy_request(request, target_url)
        elif path.startswith("/api/research/"):
            target_url = f"{self.research_url}{path.replace('/api/research', '')}"
            return await self._proxy_request(request, target_url)
        
        return await call_next(request)

    async def _proxy_request(self, request: Request, target_url: str) -> Response:
        req_headers = dict(request.headers)
        # Remove host header to avoid issues with proxying
        if "host" in req_headers:
            del req_headers["host"]

        try:
            proxy_response = await self.client.request(
                request.method,
                target_url,
                headers=req_headers,
                params=request.query_params,
                content=await request.body(),
                follow_redirects=False,
            )
            # Create a StreamingResponse to avoid loading the whole content into memory
            return StreamingResponse(
                proxy_response.aiter_bytes(),
                status_code=proxy_response.status_code,
                headers=proxy_response.headers,
            )
        except httpx.ConnectError as e:
            return Response(f"Proxy connection error: {e}", status_code=500)
        except Exception as e:
            return Response(f"Proxy error: {e}", status_code=500)
