# HERMES Hybrid Inference Strategy
> Anthropic for interactive, Ollama for autonomous (when ready)

## Current State (Apr 22, 2026)

**Active:** Anthropic (Claude) — all tasks
**Standby:** Ollama — ready for integration when installed

---

## Architecture: Hybrid Model

```
User (Matt)
    ↓
[Interactive Requests] → HERMES (Anthropic) → Fast response (<2s)
    ↓
[Autonomous Tasks] → HERMES (Ollama when ready) → Local inference
    ├─ Morning briefing (6 AM)
    ├─ Hourly status (RTH)
    ├─ EOD analysis (4 PM)
    ├─ Daily perf check (9 PM)
    └─ Weekly analysis (Fri 5 PM)
    ↓
[Critical Alerts] → Anthropic (always, for speed)
```

---

## Why Hybrid?

| Task Type | Current | Target | Reason |
|-----------|---------|--------|--------|
| **Interactive** (you ask me now) | Anthropic | Anthropic | Speed + reasoning |
| **Autonomous** (cron jobs) | Anthropic | Ollama | Cost + privacy |
| **Critical Alerts** (kill switch) | Anthropic | Anthropic | Always fast |

---

## Ollama Setup (When Ready)

### Prerequisites
- Hardware: Intel i7/M1+ recommended
- RAM: 16GB+ (for 13B models)
- Disk: 20GB+ free
- OS: Windows (via WSL2), macOS, Linux

### Installation
```bash
# Download from https://ollama.ai
# Run installer for your OS

# Verify
ollama --version

# Start Ollama server (runs on localhost:11434)
ollama serve

# Pull a model (run in new terminal)
ollama pull mistral:7b    # Fast, balanced
# OR
ollama pull llama2:13b    # Better reasoning
```

### Which Model?
- **Mistral 7B**: 4-5s per task, ~4GB RAM — good for background work
- **Llama2 13B**: 8-10s per task, ~8GB RAM — better quality analysis
- **Llama2 70B**: 20-30s per task, 40GB+ RAM — overkill, not needed

**Recommendation:** Start with Mistral 7B. If latency >5s, revisit.

---

## Integration: Anthropic → Ollama Bridge

Once Ollama is installed, we'll:

1. **Modify cron job prompts** to route to local Ollama endpoint
2. **Add fallback logic** — if Ollama down, use Anthropic
3. **Keep auth** — API key still works for critical alerts
4. **Measure latency + cost** — compare weekly

### Code Sketch (Pseudo)
```python
async def run_autonomous_task(prompt):
    """Route to Ollama, fallback to Anthropic"""
    try:
        # Try local Ollama first (port 11434)
        response = await ollama.generate(
            model="mistral:7b",
            prompt=prompt,
            timeout=10
        )
        return response
    except (ConnectionError, TimeoutError):
        # Fallback to Anthropic
        response = client.messages.create(
            model="claude-sonnet-4.6",
            prompt=prompt
        )
        return response
```

---

## Performance Tracking

### Metrics We're Measuring

**Daily (9 PM CT):**
- Latency per task (ms)
- Token cost (USD)
- Completion rate (%)
- Alert accuracy (%)

**Weekly (Friday 5 PM CT):**
- Avg latency vs benchmark
- Total cost vs Ollama estimate
- Ollama readiness (if installed)
- Recommendation for next week

### Decision Tree (Apr 29)

```
Do we have Ollama installed and tested?
  ├─ YES + latency <5s + reliability >95%
  │   → MIGRATE to hybrid (Ollama for autonomous)
  │   → Est. savings: $5-10/week
  │
  ├─ YES + latency >5s OR reliability <95%
  │   → STAY with Anthropic
  │   → Revisit after hardware upgrade
  │
  └─ NO (still not installed)
      → STAY with Anthropic
      → Provide setup guide + timeline
```

---

## Cost Analysis (Preliminary)

### Anthropic (Current)
- Morning briefing: ~500 tokens → $0.0015
- EOD analysis: ~800 tokens → $0.0024
- Hourly checks: ~300 tokens → $0.0009
- Daily perf check: ~400 tokens → $0.0012
- **Est. daily cost: ~$0.02-0.03**
- **Est. monthly cost: $0.60-0.90**

### Ollama (Local, No API Costs)
- Electricity only (~$0.01-0.05/day depending on hardware)
- No API calls = no token spend
- **Est. monthly cost: $0.30-1.50**
- **Weekly savings vs Anthropic: $5-10**

---

## Timeline

| Date | Action | Owner |
|------|--------|-------|
| Apr 22 | Set up hybrid tracking + monitoring | HERMES ✓ |
| Apr 23-28 | Collect baseline metrics (Anthropic only) | HERMES |
| Apr 29 | Weekly analysis + decision | HERMES |
| May 1 (if approved) | Install Ollama + test integration | You |
| May 2-8 | Parallel testing (Anthropic vs Ollama) | HERMES |
| May 9 | Final recommendation + cutover plan | HERMES |

---

## Next Steps

1. **Review performance data** as it arrives (daily Telegram alerts)
2. **Decide on Ollama timing** — install this week? Next week?
3. **Provide hardware specs** — RAM, CPU so I can recommend the right model
4. **Watch weekly summaries** — I'll tell you if the data supports the switch

**Bottom line:** You're not locked in. If Anthropic cost is low and latency is good, we stay. If we find Ollama cuts costs significantly without sacrificing speed, we migrate. The data will tell us.

Ready to ride?

---

**Files to Track:**
- `/mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/docs/HERMES_PERFORMANCE_TRACKING.md` — daily/weekly metrics
- `/mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/docs/HERMES_INFERENCE_STRATEGY.md` — this file
- Telegram alerts — performance reports daily at 9 PM, weekly at 5 PM Friday

**Questions?** Ask me anytime. I'll loop the latest data into my response.
