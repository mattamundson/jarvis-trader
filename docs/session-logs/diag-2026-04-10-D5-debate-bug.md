# Debug Report: BullResearcherAgent LLM Interface Error (Intermittent)

**Date:** 2026-04-10  
**Agent:** D5 (Read-only investigation)  
**Issue:** "Agent BullResearcherAgent exposes no callable LLM interface (_call_llm, call_llm, _client, client)" — intermittent, 19 errors in current session, system continues functioning  

## Root Cause Analysis

**VERIFIED FACTS:**
- `BullResearcherAgent._call_llm()` exists at `engine/agents/bull_researcher.py:301` — async, 23 lines
- `BullResearcherAgent.call_llm()` exists at `engine/agents/bull_researcher.py:167` — async, 39 lines
- Fresh instance probe confirms both methods present and callable (verified in earlier session)
- Agents instantiated once at startup in `main.py:433-434` and stored in `TradingPipeline.agents` dict
- No agent wrapping, proxying, or dynamic reloading in production code
- No `__getattr__`, `__slots__`, or descriptors that would hide attributes

**ERROR SOURCE:**
Probe in `debate.py:889-910` (`_call_agent_llm` function):
```python
method = getattr(agent, method_name, None)
if callable(method):
    ...
else:
    raise RuntimeError(f"Agent {type(agent).__name__} exposes no callable...")
```

The `getattr()` is returning `None` for both `_call_llm` and `call_llm`, yet the methods are definitely defined.

## Hypotheses Tested

| Hypothesis | Status | Evidence |
|-----------|--------|----------|
| H1: Agent wrapper/proxy hiding attributes | **RULED OUT** | TokenProxy doesn't wrap agents; ICWeightedEnsemble is a simple data container with no `__getattr__` |
| H2: Dynamic module reloading | **RULED OUT** | No `importlib.reload()` in production code (only in tests) |
| H3: Async task race condition | **POSSIBLE** | Errors cluster when multiple debates run (MES+MCL same timestamp); could indicate concurrent access issue |
| H4: Garbage collection edge case | **POSSIBLE** | Agent reference might be invalidated if exception during debate causes cleanup |
| H5: Exception during `getattr()` caught silently | **PLAUSIBLE** | If `getattr()` itself raises (e.g., descriptor error), it would propagate as type mismatch |

## System Behavior (Evidence)

- Errors cluster at times when multiple symbols run debate simultaneously (e.g., MES + MCL at 22:41:14)
- Both `_score_argument` (Rounds 2-3) AND `_rebuttal` fail on same symbol in same debate run
- System gracefully falls back: scoring defaults to 5/10, rebuttals to empty string
- Despite errors, pipeline continues and produces real verdicts (e.g., AAPL decision #2186 scored BULL_WINS with specific scores)
- No indication agents are garbage-collected or replaced

## Phase 1 Recommended Fix

**SHORT TERM (low-risk, non-blocking):**
1. Add defensive check before probe — log agent type and attributes:
   ```python
   logger.debug(f"[Debate] Probing {type(agent).__name__}: dir={dir(agent)}")
   ```
   This will capture agent state when error occurs, enabling diagnosis in next session.

2. Add 3-second retry with exponential backoff in `_call_agent_llm()`:
   ```python
   for attempt in range(3):
       method = getattr(agent, method_name, None)
       if callable(method):
           # Success path
       if attempt < 2:
           await asyncio.sleep(0.1 * (2 ** attempt))
   ```

**MEDIUM TERM (requires investigation):**
- Check if agents are being accessed from multiple async tasks concurrently
- Verify agent instantiation happens atomically (no partial init race)
- Audit `pipeline.py` to see if agents dict is ever mutated after startup

## Impact

- **Severity:** Low — graceful fallback to defaults, no trading impact
- **Frequency:** Intermittent, clustered (suggests concurrent access pattern)
- **Workaround:** Restart engine to clear any phantom state

## Files Involved

- `engine/agents/debate.py:877-910` — probe logic (where error raised)
- `engine/agents/debate.py:816, 865` — callers (catch and log)
- `engine/agents/bull_researcher.py:167, 301` — method definitions
- `engine/agents/bear_researcher.py` — identical pattern, same symptoms
- `engine/agents/pipeline.py:1266-1289` — agent retrieval and debate setup

## Conclusion

The methods ARE present on fresh instances. The intermittency and clustering pattern suggests either:
1. A race condition when multiple debates run in parallel, OR
2. A subtle edge case in Python's attribute resolution under high concurrency

Adding debug logging (as recommended above) will capture the agent state at failure time, enabling root-cause determination in the next live session.
