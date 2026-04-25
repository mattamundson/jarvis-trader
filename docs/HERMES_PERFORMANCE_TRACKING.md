# HERMES Performance & ROI Tracking
> Weekly analysis of inference strategy, system costs, and effectiveness

## Week 1: Apr 22-29, 2026

### Metrics Tracked

| Metric | Target | Unit | Status |
|--------|--------|------|--------|
| **Inference Latency** | <2s (interactive), <5s (background) | seconds | TBD |
| **Cost per Briefing** | <$0.05 | USD | TBD |
| **Briefing Accuracy** | >95% (levels match reality) | % | TBD |
| **Alert False Positives** | <5% | % | TBD |
| **Task Completion Rate** | >90% (cron jobs) | % | TBD |
| **System Uptime** | >99% | % | TBD |
| **MCP Connectivity** | 100% (jarvis-trader) | % | TBD |

### Key Decisions to Monitor

1. **Should Ollama run autonomous tasks?**
   - Criteria: <5s latency + >90% reliability
   - Current state: Anthropic handling all tasks
   - Decision date: Apr 29

2. **Hybrid vs Pure Ollama?**
   - Cost analysis: token spend per task
   - Speed analysis: latency for time-critical tasks
   - Reliability: fallback behavior

3. **Which Ollama model?**
   - Llama2 7B: fast, lower accuracy
   - Mistral 7B: balanced
   - Llama2 13B: better reasoning
   - Local specs TBD

---

## Performance Log

### Week 1 (Apr 22-29)

#### Daily Checkpoint Format:
```
[DATE] — Morning Briefing
Latency: [ms]
Cost: $[X]
Accuracy: [high/medium/low]
Notes: [any issues]

[DATE] — EOD Analysis
Latency: [ms]
Cost: $[X]
Quality: [high/medium/low]
Notes: [any issues]
```

**Baseline (Apr 22):**
- System: Anthropic only
- Morning briefing: ~2s latency (estimated)
- EOD analysis: ~3s latency (estimated)
- Cost baseline: TBD (calculate after first week)

---

## Analysis Schedule

**Every Day at 9:00 PM CT:**
- HERMES reviews that day's metrics
- Flags any anomalies (latency spike, accuracy drop, cost surge)
- Auto-logs to this file

**Every Friday at 5:00 PM CT:**
- HERMES generates weekly summary
- Compares Anthropic vs Ollama hypotheticals
- Recommends next week's inference strategy
- Updates decision matrix

---

## ROI Calculation Framework

**Cost Per Task:**
```
(API tokens * $0.003 per K tokens) / tasks completed = $/task
```

**Value Per Task:**
```
(Minutes saved * hourly rate) + (edge improvement % * capital)
= total value
```

**ROI = Value / Cost**

---

## Current Assumptions (To Validate)

- Anthropic cost: ~$0.03-0.05 per briefing (estimate)
- Ollama cost: $0.00 (local inference, electricity only)
- Ollama latency: +2-3s vs Anthropic (estimate)
- Ollama reliability: TBD (depends on model + hardware)
- MCP integration complexity: Medium (bridge required)

---

## Decision Tree (Apr 29)

```
IF (Ollama latency < 5s AND reliability > 95%)
  THEN: Move autonomous tasks to Ollama
  AND: Keep Anthropic for interactive/real-time
  
IF (Ollama latency >= 5s OR reliability <= 95%)
  THEN: Stay hybrid with Anthropic primary
  AND: Revisit Ollama after hardware upgrade
  
IF (Anthropic cost > $5/day)
  THEN: Ollama becomes priority (cost ROI positive)
```

---

## Notes for HERMES

- Check this file daily for what to measure
- Log metrics in "Performance Log" section
- Don't wait for Friday; alert Matt if any metric falls below threshold
- If Ollama is installed, run parallel tests (measure actual latency + reliability)
- Calculate weekly cost: (API calls * per-token-rate) / task count

---

**Next Review:** Friday, Apr 25, 2026 @ 5:00 PM CT
