# JARVIS TRADER — API Authentication & Rate Limiting

## Overview

The JARVIS TRADER FastAPI engine now includes production-grade API key authentication and request rate limiting via `slowapi`.

- **Authentication**: X-API-Key header validation with configurable keys
- **Rate Limiting**: Graduated limits per endpoint (5/min for pipeline ops, 10/min for safety, 60/min for general)
- **Exempt Endpoints**: Health, docs, and OpenAPI endpoints bypass authentication
- **Production-Ready**: Proper error responses, logging, and exception handling

---

## Configuration

### 1. Environment Variable

In `.env` (or `.env.example`):

```bash
API_KEY=[REDACTED]
```

**Default value**: `jarvis-dev-key-change-me` (change in production!)

The key is loaded from the `TradingConfig` in `config.py`:

```python
API_KEY: str = Field("jarvis-dev-key-change-me", env="API_KEY",
                     description="FastAPI X-API-Key header authentication")
```

### 2. Update Requirements

`slowapi` is already added to `requirements-core.txt`:

```bash
slowapi==0.1.9            # Rate limiting for FastAPI
```

Install with:

```bash
pip install -r requirements-core.txt
```

---

## Authentication Usage

### Request Header Format

Include the `X-API-Key` header in all protected endpoint requests:

```bash
curl -X POST http://localhost:8010/safety/kill-switch/activate \
  -H "X-API-Key: [REDACTED]"
```

### Python/httpx Example

```python
import httpx

async with httpx.AsyncClient() as client:
    headers = {"X-API-Key": "your-strong-api-key-here"}
    response = await client.post(
        "http://localhost:8010/safety/kill-switch/activate",
        headers=headers
    )
```

### JavaScript/fetch Example

```javascript
const response = await fetch('http://localhost:8010/safety/kill-switch/activate', {
  method: 'POST',
  headers: {
    'X-API-Key': 'your-strong-api-key-here'
  }
});
```

---

## Exempt Endpoints (No API Key Required)

The following endpoints **do not** require `X-API-Key`:

- `GET /health` — Quick health check
- `GET /health/full` — Comprehensive system health
- `GET /docs` — Swagger OpenAPI docs
- `GET /openapi.json` — OpenAPI specification
- `GET /redoc` — ReDoc documentation

These are safe to call without authentication for monitoring and documentation purposes.

---

## Rate Limiting

Requests are limited based on endpoint category:

### Rate Limit Tiers

| Tier | Limit | Endpoints |
|------|-------|-----------|
| Safety | 10/minute | `/safety/*` |
| Pipeline | 5/minute | `/pipeline/run` (reserved for future) |
| General | 60/minute | All other protected endpoints |

### Example: Exceeding a Rate Limit

```bash
curl -X GET http://localhost:8010/safety/status \
  -H "X-API-Key: your-key" \
  -H "Accept: application/json"

# After 10 requests in 60 seconds:
# HTTP/1.1 429 Too Many Requests
# {
#   "detail": "Rate limit exceeded. Please try again later.",
#   "status": 429
# }
```

### Rate Limit Headers

slowapi may include rate limit information in response headers:

```
RateLimit-Limit: 10
RateLimit-Remaining: 5
RateLimit-Reset: 1234567890
```

(Note: Header support depends on slowapi version and backend storage)

---

## Implementation Details

### File Structure

```
engine/
├── config.py                    # API_KEY field in TradingConfig
├── main.py                      # App initialization with auth + rate limiting
├── requirements-core.txt        # slowapi dependency
├── .env.example                 # API_KEY example
└── middleware/
    ├── __init__.py              # Empty package marker
    ├── auth.py                  # X-API-Key dependency
    └── rate_limit.py            # slowapi configuration
```

### Authentication Dependency (`middleware/auth.py`)

The `verify_api_key()` function is a FastAPI dependency that:

1. Checks for the `X-API-Key` header
2. Skips validation for exempt paths (health, docs)
3. Returns 401 if the key is missing or invalid
4. Logs all auth attempts (debug for success, warning for failures)

```python
from fastapi import Depends
from middleware.auth import verify_api_key

@app.get("/some/protected/endpoint")
async def protected_route(_: str = Depends(verify_api_key)):
    return {"message": "authenticated"}
```

### Rate Limiter (`middleware/rate_limit.py`)

Uses `slowapi.Limiter` with:

- **Storage**: In-memory (suitable for single-process deployments)
- **Key Function**: `get_remote_address()` (rate limit by IP)
- **Custom Handler**: Returns JSON 429 instead of HTML

Apply to routes:

```python
from middleware.rate_limit import limiter

@app.get("/endpoint")
@limiter.limit("10/minute")
async def endpoint(request: Request):
    return {}
```

---

## Deployment Checklist

### Development

- Use default key: `jarvis-dev-key-change-me`
- In-memory rate limiting is fine
- Test with: `pytest tests/test_auth_and_rate_limit.py`

### Staging

- Generate a strong API key (e.g., `openssl rand -hex 32`)
- Set `API_KEY` in `.env`
- Test all protected endpoints with the new key
- Monitor rate limit behavior under load

### Production

- **Mandatory**: Change API_KEY to a strong, random value
- Consider using a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
- For multi-process deployments, consider swapping in-memory storage for Redis:
  ```python
  from slowapi.util import get_remote_address
  limiter = Limiter(
      key_func=get_remote_address,
      storage_uri="redis://localhost:6379"  # Add Redis storage
  )
  ```
- Increase rate limits if needed based on actual usage patterns
- Log and monitor 401/429 responses for security audits

---

## Endpoints Protected by Authentication

All endpoints **except health, docs, and OpenAPI** require `X-API-Key`:

### Safety Endpoints (10/minute)

- `POST /safety/kill-switch/activate`
- `POST /safety/kill-switch/deactivate`
- `GET /safety/status`
- `GET /safety/circuit-breakers`
- `GET /safety/config`
- `POST /safety/reset-daily-pnl`

### Analysis Endpoints (60/minute)

- `POST /analyze/technical`

### Portfolio Endpoints (60/minute)

- `POST /portfolio/paper/trade`

### Decision Logging (60/minute)

- `POST /decisions/log`

---

## Error Responses

### 401 Unauthorized (Missing or Invalid API Key)

```json
{
  "detail": "Invalid or missing API key"
}
```

Headers:
```
WWW-Authenticate: Bearer
```

### 429 Too Many Requests (Rate Limited)

```json
{
  "detail": "Rate limit exceeded. Please try again later.",
  "status": 429
}
```

---

## Testing

### Manual Testing

```bash
# Without API key (should fail)
curl -X POST http://localhost:8010/safety/kill-switch/activate

# With invalid key (should fail)
curl -X POST http://localhost:8010/safety/kill-switch/activate \
  -H "X-API-Key: wrong-key"

# With valid key (should succeed or fail at next layer)
curl -X POST http://localhost:8010/safety/kill-switch/activate \
  -H "X-API-Key: [REDACTED]"

# Health check (no key needed)
curl http://localhost:8010/health
```

### Automated Testing

Run the test suite:

```bash
pytest tests/test_auth_and_rate_limit.py -v
```

Tests cover:
- Missing API key validation
- Invalid API key rejection
- Valid key acceptance
- Health endpoint exemption
- OpenAPI docs exemption
- Rate limit enforcement

---

## Monitoring & Logging

### Log Levels

**Debug logs** (when valid key accepted):
```
DEBUG jarvis_trader.auth: ✅ Valid API key for path: /safety/status
```

**Warning logs** (on auth failures):
```
WARNING jarvis_trader.auth: Missing X-API-Key header for path: /safety/status
WARNING jarvis_trader.auth: Invalid X-API-Key attempt for path: /safety/status
WARNING jarvis_trader.rate_limit: Rate limit exceeded for 127.0.0.1 on /safety/status
```

### Recommended Alerts

In production, create alerts for:

1. **Repeated 401 errors** (possible security probe)
2. **Repeated 429 errors** (possible brute force or legitimate traffic surge)
3. **Different API keys in logs** (possible key rotation)

---

## Security Considerations

### Key Management

- **Never commit API keys** to version control
- Use `.env` file (already in `.gitignore`)
- Rotate keys periodically in production
- Use a secrets manager for sensitive deployments

### Rate Limiting

- In-memory storage is **not suitable for distributed systems**
- For multi-instance deployments, use Redis or similar distributed cache
- Adjust limits based on your actual trading volume and API usage patterns

### HTTPS

In production, **always use HTTPS**. The `X-API-Key` header is transmitted as plaintext in HTTP requests.

### CORS

CORS is configured to allow requests from:
- `http://localhost:3010`
- `http://localhost:3000`
- `http://localhost:3004`

Update `main.py` for production domains:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Troubleshooting

### "Invalid or missing API key" on Valid Key

1. Check for typos in the key
2. Verify the key in `.env` matches exactly (including case)
3. Ensure you're using the `X-API-Key` header (not `Authorization` or `API-Key`)
4. Check logs for exact error: `grep -i "invalid.*api" logs/`

### "Rate limit exceeded" Despite Low Request Volume

1. Check if other instances are hitting the same endpoint (distributed system)
2. Verify you're on the correct rate tier (e.g., safety = 10/min, general = 60/min)
3. Check client logs for retry loops or duplicate requests
4. Consider increasing limits if legitimate traffic is being blocked

### Auth Dependency Not Being Applied

1. Verify `Depends(verify_api_key)` is in the route signature
2. Check that `@limiter.limit()` decorator comes **before** the dependency
3. Ensure imports are correct: `from middleware.auth import verify_api_key`

---

## Future Enhancements

Potential improvements for future versions:

- **JWT tokens** instead of simple API keys
- **OAuth 2.0 integration** for third-party access
- **API key scoping** (e.g., read-only keys)
- **Rate limiting per key** (instead of per IP)
- **Webhook signatures** for incoming TradingView alerts
- **Request logging/audit trail** for compliance

---

For questions or issues, refer to the JARVIS TRADER documentation or contact the development team.
