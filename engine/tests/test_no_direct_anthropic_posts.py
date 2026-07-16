"""I8: architecture regression -- no direct Anthropic POSTs outside the allowlist.

Root cause of the 2026-06 outage class (B1/B2/B4): agents making raw httpx
POSTs to the Anthropic REST endpoint bypass JarvisLLMClient and with it the
Anthropic -> Vertex -> Gemini -> OpenAI fallback chain, provider health, and
cost tracking. When Anthropic credits ran out, every bypassing agent failed
while routed agents kept working on the fallback.

This test makes the invariant structural: any NEW file under engine/agents/
or engine/discord/ containing the REST URL literal fails CI until it either
routes through the client or earns a documented allowlist entry.

2026-07-15: a second, distinct bypass shape was found live in
DebateOrchestrator._score_confluence and PostTradeAnalyzer.analyze_trade --
both called the Anthropic SDK object directly via
`<JarvisLLMClient instance>.client.messages.create(...)`, skipping .call()
and its fallback/retry/cost-tracking entirely. This never contains the
REST URL literal in source (the SDK, not this code, owns that string), so
test_no_unallowlisted_anthropic_url_literals never caught it -- both ran
Anthropic-only for weeks, one of them (the confluence scorer) silently
forcing every debate to INCONCLUSIVE during the outage. See
test_no_unallowlisted_raw_sdk_message_create below for the second invariant
that closes this gap.
"""

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent

# The URL literal that grants raw-call capability. Bare "api.anthropic.com"
# mentions in comments/error-parsers are fine; building the full REST URL is
# what this invariant polices.
URL_LITERAL = "https://api.anthropic.com"

SCAN_DIRS = ("agents", "discord")

# Documented exceptions. Every entry must (a) still contain the URL literal
# (stale entries fail test_allowlist_is_current) and (b) keep its primary
# path routed through the client where marked guarded=True
# (test_guarded_fallbacks_keep_primary_guard).
ALLOWLIST = {
    # Guarded fallbacks: primary path is self._llm.call(); raw POST only fires
    # when the injected client is not a JarvisLLMClient (standalone/CLI use).
    "agents/news_analyst.py": {"guarded": True},
    "agents/social_analyst.py": {"guarded": True},
    # B4 exception: standalone contexts (CLI import, MCP server, briefing)
    # construct CoreyCommentaryProcessor without an engine LLM client.
    "discord/commentary_processor.py": {"guarded": True},
    # B4-documented dark paths: not on the live pipeline decision path.
    "agents/tail_risk_researcher.py": {"guarded": False},
    "agents/managed_agent_bridge.py": {"guarded": False},
    # Doc-only mentions (no call capability): the URL appears in a docstring
    # example (credit-exhaustion detector) / a regex doc comment respectively.
    "agents/pipeline.py": {"guarded": False},
    "discord/hermes_upgrade/appliers/config_patcher.py": {"guarded": False},
}

# Decision-path agents fixed in B1/B2: these must never reference the
# Anthropic API host again in ANY form (URL, comment, or otherwise).
DECISION_AGENTS = (
    "agents/trader.py",
    "agents/risk_manager.py",
    "agents/fund_manager.py",
)

GUARD_MARKER = 'hasattr(self._llm, "call")'

# Second bypass shape: calling the wrapped Anthropic SDK client's
# .messages.create(...) directly instead of going through .call(). No
# allowlist entries exist -- every prior instance (debate.py, post_mortem.py)
# was a genuine bug, not a deliberate exception, so any new occurrence should
# fail outright rather than be silently permitted.
SDK_BYPASS_PATTERN = ".client.messages.create("
SDK_BYPASS_ALLOWLIST: dict[str, dict] = {}


def _scan_files():
    for d in SCAN_DIRS:
        yield from (ENGINE_ROOT / d).rglob("*.py")


def _rel(path: Path) -> str:
    return path.relative_to(ENGINE_ROOT).as_posix()


def test_no_unallowlisted_anthropic_url_literals():
    offenders = []
    for path in _scan_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if URL_LITERAL in text and _rel(path) not in ALLOWLIST:
            offenders.append(_rel(path))
    assert not offenders, (
        f"Direct Anthropic REST URL found outside the allowlist: {offenders}. "
        "Route the call through JarvisLLMClient.call() (engine/llm/client.py) "
        "so it inherits the provider fallback chain -- or, if this is a "
        "deliberate non-pipeline path, add a documented ALLOWLIST entry in "
        "this test."
    )


def test_allowlist_is_current():
    stale = []
    for rel in ALLOWLIST:
        path = ENGINE_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file missing)")
            continue
        if URL_LITERAL not in path.read_text(encoding="utf-8", errors="replace"):
            stale.append(f"{rel} (no longer contains the URL -- prune the entry)")
    assert not stale, f"Stale allowlist entries: {stale}"


def test_guarded_fallbacks_keep_primary_guard():
    broken = []
    for rel, meta in ALLOWLIST.items():
        if not meta["guarded"]:
            continue
        text = (ENGINE_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if GUARD_MARKER not in text:
            broken.append(rel)
    assert not broken, (
        f"Guarded-fallback files lost their client-first guard: {broken}. "
        "The raw POST may only run when the injected client lacks .call()."
    )


def test_no_unallowlisted_raw_sdk_message_create():
    """Catches the bypass shape the URL-literal check above can't see: calling
    the wrapped Anthropic SDK client's .messages.create(...) directly instead
    of JarvisLLMClient.call(). Found live in _score_confluence and
    PostTradeAnalyzer.analyze_trade (2026-07-15) -- both ran Anthropic-only,
    with no fallback, for weeks."""
    offenders = []
    for path in _scan_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if SDK_BYPASS_PATTERN in text and _rel(path) not in SDK_BYPASS_ALLOWLIST:
            offenders.append(_rel(path))
    assert not offenders, (
        f"Raw Anthropic SDK call found outside the allowlist: {offenders}. "
        "Route the call through JarvisLLMClient.call() (engine/llm/client.py) "
        "so it inherits the provider fallback chain, retries, and cost "
        "tracking -- or, if this is a deliberate exception, add a documented "
        "SDK_BYPASS_ALLOWLIST entry in this test."
    )


def test_decision_agents_never_reference_anthropic_host():
    offenders = []
    for rel in DECISION_AGENTS:
        text = (ENGINE_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if "api.anthropic.com" in text:
            offenders.append(rel)
    assert not offenders, (
        f"B1/B2 regression: decision-path agents reference the Anthropic API "
        f"host again: {offenders}. All LLM traffic must go through "
        "JarvisLLMClient.call()."
    )
