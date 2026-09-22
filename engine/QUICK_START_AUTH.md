# JARVIS TRADER Authentication — Quick Start Guide

## Installation (1 minute)

1. Install slowapi:
```bash
pip install slowapi==0.1.9
# Or update all dependencies:
pip install -r requirements-core.txt
```

2. Set API key in `.env`:
```bash
API_KEY=[REDACTED]
```

3. Start the server:
```bash
uvicorn main:app --reload --port 8010
```

---

## Testing (30 seconds)

### Health (no auth required)
```bash
curl http://localhost:8010/health
# Response: {"status": "ok", ...}
```

### Protected endpoint without key (should fail)
```bash
curl -X POST http://localhost:8010/safety/kill-switch/activate
# Response: {"detail": "Invalid or missing API key"} [401]
```

### Protected endpoint with key (should succeed)
```bash
curl -X POST http://localhost:8010/safety/kill-switch/activate \
  -H "X-API-Key: [REDACTED]"
# Response: {...} or 500+ if dependencies missing (but NOT 401!)
```

### OpenAPI Docs (no auth required)
```
http://localhost:8010/docs
```

---

## Python Client Example

```python
import httpx

api_key = "[REDACTED]"

async with httpx.AsyncClient() as client:
    # Protected endpoint
    response = await client.post(
        "http://localhost:8010/safety/kill-switch/activate",
        headers={"X-API-Key": api_key}
    )
    print(response.json())

    # Health check (no key needed)
    response = await client.get("http://localhost:8010/health")
    print(response.json())
```

---

## Rate Limits

- **Safety endpoints**: 10 requests/minute
- **Other endpoints**: 60 requests/minute

Hitting a limit returns:
```json
{
  "detail": "Rate limit exceeded. Please try again later.",
  "status": 429
}
```

---

## Production Setup

1. Generate strong API key:
```bash
openssl rand -hex 32
```

2. Set in `.env`:
```bash
API_KEY=[REDACTED]
```

3. Update CORS in `main.py` for your domain:
```python
allow_origins=["https://yourdomain.com"]
```

4. Use HTTPS in production!

---

## Endpoints Protected by API Key

### Safety (10/min)
- `POST /safety/kill-switch/activate`
- `POST /safety/kill-switch/deactivate`
- `GET /safety/status`
- `GET /safety/circuit-breakers`
- `GET /safety/config`
- `POST /safety/reset-daily-pnl`

### Analysis (60/min)
- `POST /analyze/technical`

### Portfolio (60/min)
- `POST /portfolio/paper/trade`

### Decisions (60/min)
- `POST /decisions/log`

---

## Exempted Endpoints (no API key needed)

- `GET /health`
- `GET /health/full`
- `GET /docs`
- `GET /openapi.json`
- `GET /redoc`

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 on valid key | Check exact key match (case-sensitive), use `X-API-Key` header |
| 429 rate limited | Wait 60 seconds or increase limit in `middleware/rate_limit.py` |
| Docs still require key | They shouldn't — check your exact path matches `/docs` |

---

## See Also

- `AUTH_AND_RATE_LIMIT.md` — Full documentation
- `tests/test_auth_and_rate_limit.py` — Test examples
- `middleware/auth.py` — Authentication logic
- `middleware/rate_limit.py` — Rate limiting logic

---

Done! Your API is now secured. 🔒
