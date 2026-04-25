# HERMES Ollama Integration Architecture

## Current Status (Apr 22, 2026 11:30 PM CT)

- ✅ Ollama installed on Windows
- ✅ Ollama server running on `localhost:11434`
- ⏳ Model pull in progress (Mistral 7B or Llama2 13B)
- ⏳ HERMES configuration pending model availability

---

## Integration Design

### Request Flow

```
User (Matt) / Cron Job
    ↓
[HERMES Task]
    ↓
[Router: Is Ollama available?]
    ├─ YES → Call Ollama locally (localhost:11434)
    │         └─ Return response in <5s
    │
    └─ NO → Fallback to Anthropic API
            └─ Return response + log failure
```

### Task Routing

| Task Type | Latency Target | Routed To | Fallback |
|-----------|----------------|-----------|----------|
| Morning briefing | <5s | Ollama | Anthropic |
| Hourly checks | <3s | Ollama | Anthropic |
| EOD analysis | <5s | Ollama | Anthropic |
| Trade logging | <2s | Ollama | Anthropic |
| Critical alerts | <1s | Anthropic | N/A |
| Interactive (you ask) | <2s | Anthropic | Ollama |

---

## Configuration Files to Create

### 1. `engine/config/inference.py`

```python
# Inference provider configuration
INFERENCE_PROVIDERS = {
    "primary": "ollama",      # Use Ollama for autonomous
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_model": "mistral:7b",  # Or llama2:13b
    "fallback": "anthropic",  # Use Anthropic if Ollama fails
    "timeout_seconds": 10,
}

# Task-specific overrides
TASK_INFERENCE = {
    "morning_briefing": "ollama",
    "hourly_check": "ollama",
    "eod_analysis": "ollama",
    "trade_decision_logging": "ollama",
    "critical_alert": "anthropic",  # Always fast
    "interactive": "anthropic",     # Always responsive
}
```

### 2. `engine/utils/inference_router.py`

```python
import httpx
import logging
from config.inference import INFERENCE_PROVIDERS, TASK_INFERENCE

logger = logging.getLogger("jarvis_trader.inference")

async def call_ollama(prompt: str, timeout: int = 10) -> str:
    """Call local Ollama instance"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{INFERENCE_PROVIDERS['ollama_host']}/api/generate",
                json={
                    "model": INFERENCE_PROVIDERS['ollama_model'],
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()["response"]
    except Exception as e:
        logger.warning(f"Ollama failed: {e}. Falling back to Anthropic.")
        return None

async def call_anthropic(prompt: str) -> str:
    """Fallback to Anthropic API"""
    from llm.client import JarvisLLMClient
    client = JarvisLLMClient()
    return await client.generate(prompt)

async def route_task(task_name: str, prompt: str) -> str:
    """Route task to appropriate inference provider with fallback"""
    provider = TASK_INFERENCE.get(task_name, INFERENCE_PROVIDERS["primary"])
    
    if provider == "ollama":
        result = await call_ollama(prompt)
        if result:
            return result
    
    # Fallback to Anthropic
    return await call_anthropic(prompt)
```

### 3. Integration into Cron Jobs

**Modify `engine/main.py` → lifespan startup:**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup
    from utils.inference_router import test_ollama_connection
    
    ollama_status = await test_ollama_connection()
    if ollama_status:
        logger.info("✓ Ollama is available. Using local inference.")
    else:
        logger.warning("✗ Ollama unavailable. Falling back to Anthropic.")
    
    yield
    
    # On shutdown
    logger.info("Shutting down.")
```

---

## Testing Ollama Connection

```bash
# Test from terminal
curl http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral:7b",
    "prompt": "What is 2+2?",
    "stream": false
  }'

# Expected response:
# {"response": " 2 + 2 = 4\n", ...}
```

---

## Performance Expectations

### Ollama (Local)

| Model | RAM Required | Latency | Quality |
|-------|--------------|---------|---------|
| Mistral 7B | 8GB | 3-5s per task | Good |
| Llama2 13B | 16GB | 8-12s per task | Better |

### Anthropic (Cloud)

| Model | Cost | Latency | Quality |
|-------|------|---------|---------|
| Claude 3.5 Sonnet | $0.003/K tokens | <1s | Excellent |

---

## Cost Analysis (Updated)

### Before (Anthropic Only)
- Morning briefing: 500 tokens × $0.003 = $0.0015
- EOD analysis: 800 tokens × $0.003 = $0.0024
- Hourly checks: 300 tokens × $0.003 = $0.0009 (×24 = $0.216/day)
- **Total: ~$0.60-0.90/month**

### After (Ollama Primary)
- All local tasks: $0.00 (electricity negligible)
- Anthropic fallback: ~$0.01/month (rare)
- **Total: ~$0.00/month**

### Savings
- **$0.60-0.90/month saved**
- **Full privacy + control**
- **Zero API limits**

---

## Rollout Plan

1. ✅ Ollama installed and running
2. ⏳ Model pulled (waiting on you)
3. ⏳ Test connection (once model available)
4. ⏳ Deploy inference router
5. ⏳ Update cron jobs to use Ollama
6. ⏳ Complete top 3 builds (Trade logging, Calendar, Telegram)
7. ✅ Monitor performance (daily + weekly)

---

## Next Steps (After Model Pulled)

1. **Test:** Verify Ollama can generate text
2. **Deploy:** Update cron jobs to use local Ollama
3. **Build:** Complete Trade Decision Logging, Economic Calendar, Telegram Bridge
4. **Monitor:** Daily performance checks (latency, accuracy, uptime)

---

**Status: Ready to execute once model is pulled.**

See `/mnt/c/Users/mattm/PULL_MODEL_NOW.md` for next steps.
